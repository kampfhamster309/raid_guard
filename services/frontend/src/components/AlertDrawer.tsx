import { useEffect, useState } from "react";
import type { Alert, AlertEnrichment } from "../types";
import { SeverityBadge } from "./SeverityBadge";
import { blockDomain, fetchLlmSettings, fetchPiholeSettings, reEnrichAlert } from "../api";

interface Props {
  alert: Alert | null;
  onClose: () => void;
}

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex gap-2 py-1.5 border-b border-slate-700 last:border-0">
      <span className="w-28 shrink-0 text-slate-400 text-xs">{label}</span>
      <span className="text-slate-200 text-xs font-mono break-all">
        {value ?? "—"}
      </span>
    </div>
  );
}

/** Try to extract a queried domain from EVE JSON (DNS events). */
function extractDomain(rawJson: Record<string, unknown> | null): string {
  if (!rawJson) return "";
  const dns = rawJson.dns as Record<string, unknown> | undefined;
  if (dns) {
    const query = dns.query as Array<{ rrname?: string }> | undefined;
    if (Array.isArray(query) && query[0]?.rrname) return String(query[0].rrname);
    if (typeof dns.rrname === "string") return dns.rrname;
  }
  return "";
}

export function AlertDrawer({ alert, onClose }: Props) {
  const [piholeConfigured, setPiholeConfigured] = useState(false);
  const [blockInput, setBlockInput] = useState("");
  const [blocking, setBlocking] = useState(false);
  const [blockStatus, setBlockStatus] = useState<"idle" | "success" | "error">("idle");
  const [blockMessage, setBlockMessage] = useState<string | null>(null);

  const [llmConfigured, setLlmConfigured] = useState(false);
  const [enrichmentJson, setEnrichmentJson] = useState<AlertEnrichment | null>(null);
  const [enriching, setEnriching] = useState(false);
  const [enrichError, setEnrichError] = useState<string | null>(null);

  useEffect(() => {
    if (!alert) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [alert, onClose]);

  // Reset all transient state and reload settings whenever a new alert is opened.
  useEffect(() => {
    if (!alert) return;
    setBlockStatus("idle");
    setBlockMessage(null);
    setBlockInput(extractDomain(alert.raw_json));
    setEnrichmentJson(alert.enrichment_json);
    setEnrichError(null);

    fetchPiholeSettings()
      .then((s) => setPiholeConfigured(s.configured && s.enabled))
      .catch(() => setPiholeConfigured(false));

    fetchLlmSettings()
      .then((s) => setLlmConfigured(s.url.trim() !== "" && s.model.trim() !== ""))
      .catch(() => setLlmConfigured(false));
  }, [alert]);

  const handleBlock = async () => {
    const domain = blockInput.trim();
    if (!domain) return;
    setBlocking(true);
    setBlockStatus("idle");
    setBlockMessage(null);
    try {
      await blockDomain(domain);
      setBlockStatus("success");
      setBlockMessage(`${domain} added to Pi-hole deny list.`);
    } catch (e) {
      setBlockStatus("error");
      setBlockMessage(e instanceof Error ? e.message : "Block failed");
    } finally {
      setBlocking(false);
    }
  };

  const handleReEnrich = async () => {
    if (!alert) return;
    setEnriching(true);
    setEnrichError(null);
    try {
      const result = await reEnrichAlert(alert.id);
      setEnrichmentJson(result);
    } catch (e) {
      setEnrichError(e instanceof Error ? e.message : "AI analysis failed");
    } finally {
      setEnriching(false);
    }
  };

  if (!alert) return null;

  return (
    <>
      {/* backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-10"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* drawer */}
      <aside
        className="fixed right-0 top-0 h-full w-full sm:w-[480px] bg-slate-900 border-l border-slate-700 z-20 flex flex-col shadow-2xl"
        role="dialog"
        aria-label="Alert detail"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <SeverityBadge severity={alert.severity} />
            <span className="text-slate-300 text-sm">Alert #{alert.id.slice(-8)}</span>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-xl leading-none"
            aria-label="Close detail"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
              Details
            </h2>
            <div className="bg-slate-800 rounded p-3">
              <Row label="Time" value={new Date(alert.timestamp).toLocaleString()} />
              <Row label="Severity" value={alert.severity} />
              <Row label="Signature" value={alert.signature} />
              <Row label="Signature ID" value={alert.signature_id} />
              <Row label="Category" value={alert.category} />
              <Row label="Src IP" value={alert.src_ip} />
              <Row label="Src port" value={alert.src_port} />
              <Row label="Dst IP" value={alert.dst_ip} />
              <Row label="Dst port" value={alert.dst_port} />
              <Row label="Protocol" value={alert.proto} />
            </div>
          </section>

          {enrichmentJson ? (
            <section>
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                AI Analysis
              </h2>
              <div className="bg-slate-800 rounded p-3 space-y-3">
                <div>
                  <p className="text-xs text-slate-500 mb-1">Summary</p>
                  <p className="text-sm text-slate-200">{enrichmentJson.summary}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500 mb-1">Severity reasoning</p>
                  <p className="text-sm text-slate-300">{enrichmentJson.severity_reasoning}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500 mb-1">Recommended action</p>
                  <p className="text-sm text-indigo-300">{enrichmentJson.recommended_action}</p>
                </div>
              </div>
            </section>
          ) : llmConfigured ? (
            <section>
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                AI Analysis
              </h2>
              <div className="bg-slate-800 rounded p-3 space-y-2">
                <p className="text-xs text-slate-400">
                  This alert was not enriched automatically. Request a one-off analysis now.
                </p>
                <button
                  onClick={() => void handleReEnrich()}
                  disabled={enriching}
                  className="px-3 py-1.5 text-xs font-medium rounded bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
                  aria-label="Request AI analysis"
                >
                  {enriching ? "Analysing…" : "Request AI Analysis"}
                </button>
                {enrichError && (
                  <p className="text-xs text-red-400">{enrichError}</p>
                )}
              </div>
            </section>
          ) : null}

          {/* Pi-hole block domain */}
          {piholeConfigured && (
            <section>
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Block Domain
              </h2>
              <div className="bg-slate-800 rounded p-3 space-y-2">
                <p className="text-xs text-slate-400">
                  Add a domain to Pi-hole's deny list (DNS sinkhole).
                </p>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={blockInput}
                    onChange={(e) => setBlockInput(e.target.value)}
                    placeholder="example.com"
                    aria-label="Domain to block"
                    className="flex-1 bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  <button
                    onClick={() => void handleBlock()}
                    disabled={blocking || !blockInput.trim() || blockStatus === "success"}
                    className="px-3 py-1.5 text-xs font-medium rounded bg-red-700 hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-white"
                  >
                    {blocking ? "Blocking…" : "Block"}
                  </button>
                </div>
                {blockMessage && (
                  <p
                    className={`text-xs ${
                      blockStatus === "success" ? "text-emerald-400" : "text-red-400"
                    }`}
                  >
                    {blockMessage}
                  </p>
                )}
              </div>
            </section>
          )}

          {alert.raw_json && (
            <section>
              <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Raw EVE JSON
              </h2>
              <pre className="bg-slate-800 rounded p-3 text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap break-all">
                {JSON.stringify(alert.raw_json, null, 2)}
              </pre>
            </section>
          )}
        </div>
      </aside>
    </>
  );
}
