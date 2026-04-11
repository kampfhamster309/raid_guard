import type { TopItem } from "../types";

interface Props {
  title: string;
  items: TopItem[];
  emptyMessage?: string;
}

export function TopListCard({ title, items, emptyMessage = "No data" }: Props) {
  const max = items[0]?.count ?? 1;

  return (
    <div className="bg-slate-800 rounded-lg p-4">
      <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="text-slate-500 text-sm">{emptyMessage}</p>
      ) : (
        <ol className="space-y-2">
          {items.map((item, idx) => (
            <li key={item.name} className="flex items-center gap-2">
              <span className="w-5 text-right text-xs text-slate-500 shrink-0">
                {idx + 1}.
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-0.5">
                  <span
                    className="text-xs text-slate-200 font-mono truncate"
                    title={item.name}
                  >
                    {item.name}
                  </span>
                  <span className="text-xs text-slate-400 ml-2 shrink-0">
                    {item.count}
                  </span>
                </div>
                <div className="h-1 rounded bg-slate-700">
                  <div
                    className="h-1 rounded bg-indigo-500"
                    style={{ width: `${(item.count / max) * 100}%` }}
                  />
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
