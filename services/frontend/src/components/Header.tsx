import type { WsStatus } from "../types";

const WS_DOT: Record<WsStatus, string> = {
  connected: "bg-green-400",
  connecting: "bg-amber-400 animate-pulse",
  disconnected: "bg-red-500",
};

const WS_LABEL: Record<WsStatus, string> = {
  connected: "Live",
  connecting: "Connecting…",
  disconnected: "Disconnected",
};

interface Props {
  wsStatus: WsStatus;
  onRefresh: () => void;
  onLogout: () => void;
}

export function Header({ wsStatus, onRefresh, onLogout }: Props) {
  return (
    <header className="flex items-center justify-between px-4 py-3 bg-slate-900 border-b border-slate-700">
      <div className="flex items-center gap-3">
        <span className="font-bold text-white tracking-tight text-lg">
          raid_guard
        </span>
        <span className="flex items-center gap-1.5 text-xs text-slate-400">
          <span
            className={`inline-block h-2 w-2 rounded-full ${WS_DOT[wsStatus]}`}
          />
          {WS_LABEL[wsStatus]}
        </span>
      </div>
      <div className="flex gap-2">
        <button
          onClick={onRefresh}
          className="rounded px-3 py-1 text-sm bg-slate-700 text-slate-200 hover:bg-slate-600 transition-colors"
          aria-label="Refresh alerts"
        >
          Refresh
        </button>
        <button
          onClick={onLogout}
          className="rounded px-3 py-1 text-sm bg-slate-700 text-slate-200 hover:bg-slate-600 transition-colors"
        >
          Logout
        </button>
      </div>
    </header>
  );
}
