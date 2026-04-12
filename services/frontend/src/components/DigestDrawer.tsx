import { useEffect } from "react";
import type { Digest, DigestContent } from "../types";
import { RiskBadge } from "./RiskBadge";
import type { RiskLevel } from "../types";

interface Props {
  digest: Digest | null;
  onClose: () => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
        {title}
      </h2>
      <div className="bg-slate-800 rounded p-3">{children}</div>
    </section>
  );
}

function BulletList({ items }: { items: string[] }) {
  if (items.length === 0) {
    return <p className="text-xs text-slate-500 italic">None</p>;
  }
  return (
    <ul className="space-y-1">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2 text-sm text-slate-200 leading-relaxed">
          <span className="text-slate-500 shrink-0">•</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

const VALID_RISK_LEVELS: RiskLevel[] = ["low", "medium", "high", "critical"];

function isRiskLevel(v: string): v is RiskLevel {
  return VALID_RISK_LEVELS.includes(v as RiskLevel);
}

export function DigestDrawer({ digest, onClose }: Props) {
  useEffect(() => {
    if (!digest) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [digest, onClose]);

  if (!digest) return null;

  let content: DigestContent | null = null;
  try {
    content = JSON.parse(digest.content) as DigestContent;
  } catch {
    // content stays null — show raw fallback
  }

  const riskLevel = digest.risk_level && isRiskLevel(digest.risk_level) ? digest.risk_level : null;
  const createdAt = new Date(digest.created_at).toLocaleString();
  const periodStart = new Date(digest.period_start).toLocaleString();
  const periodEnd = new Date(digest.period_end).toLocaleString();

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 z-10"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        className="fixed right-0 top-0 h-full w-full sm:w-[540px] bg-slate-900 border-l border-slate-700 z-20 flex flex-col shadow-2xl"
        role="dialog"
        aria-label="Digest detail"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
          <div className="flex items-center gap-2">
            {riskLevel && <RiskBadge level={riskLevel} />}
            <span className="text-slate-300 text-sm font-medium">
              Security Digest · {new Date(digest.created_at).toLocaleDateString()}
            </span>
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
          <Section title="Overview">
            <div className="space-y-1.5 text-xs">
              <div className="flex gap-2">
                <span className="w-24 shrink-0 text-slate-400">Generated</span>
                <span className="text-slate-200 font-mono">{createdAt}</span>
              </div>
              <div className="flex gap-2">
                <span className="w-24 shrink-0 text-slate-400">Period start</span>
                <span className="text-slate-200 font-mono">{periodStart}</span>
              </div>
              <div className="flex gap-2">
                <span className="w-24 shrink-0 text-slate-400">Period end</span>
                <span className="text-slate-200 font-mono">{periodEnd}</span>
              </div>
            </div>
          </Section>

          {content ? (
            <>
              <Section title="Summary">
                <p className="text-sm text-slate-200 leading-relaxed">{content.summary}</p>
              </Section>

              <Section title="Notable Incidents">
                <BulletList items={content.notable_incidents} />
              </Section>

              <Section title="Emerging Trends">
                <BulletList items={content.emerging_trends} />
              </Section>

              <Section title="Recommended Actions">
                <BulletList items={content.recommended_actions} />
              </Section>
            </>
          ) : (
            <Section title="Raw Content">
              <pre className="text-xs text-slate-300 whitespace-pre-wrap break-all">
                {digest.content}
              </pre>
            </Section>
          )}
        </div>
      </aside>
    </>
  );
}
