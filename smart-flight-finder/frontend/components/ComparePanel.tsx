"use client";

import type { StrategyPlanOut } from "@/lib/types";

/**
 * Side-by-side comparison of 2–4 plans. Minimum = 2 so a comparison exists;
 * cap at 4 to keep the table readable on a 1024px viewport.
 */
export function ComparePanel({
  plans,
  onClose,
}: {
  plans: StrategyPlanOut[];
  onClose: () => void;
}) {
  if (plans.length < 2) return null;

  const rows: Array<{ label: string; render: (p: StrategyPlanOut) => React.ReactNode }> = [
    { label: "策略", render: (p) => p.strategy },
    { label: "總價", render: (p) => `${p.currency} ${p.total_cost.toLocaleString()}` },
    { label: "分數", render: (p) => (p.score ?? "—").toString() },
    { label: "停留天數", render: (p) => `${p.total_travel_days} 天` },
    {
      label: "飛行時長 (總)",
      render: (p) => {
        const minutes = p.tickets.reduce(
          (sum, t) =>
            sum +
            t.legs.reduce(
              (s, l) => s + (new Date(l.arrival).getTime() - new Date(l.departure).getTime()) / 60000,
              0,
            ),
          0,
        );
        const h = Math.floor(minutes / 60);
        const m = Math.round(minutes % 60);
        return `${h}h ${m}m`;
      },
    },
    {
      label: "轉機次數",
      render: (p) => p.tickets.reduce((s, t) => s + t.legs.reduce((sl, l) => sl + l.stops, 0), 0),
    },
    { label: "機票數", render: (p) => p.tickets.length },
    { label: "警告", render: (p) => p.warnings.length },
    {
      label: "說明",
      render: (p) => <span className="text-xs text-slate-500">{p.explain}</span>,
    },
  ];

  return (
    <section className="rounded-xl border border-brand/40 bg-brand/5 p-4 dark:bg-brand/10">
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">比較 {plans.length} 個方案</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          收起
        </button>
      </header>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-800">
              <th className="py-2 pr-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                指標
              </th>
              {plans.map((p, i) => (
                <th
                  key={`${p.strategy}-${i}`}
                  className="py-2 pr-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500"
                >
                  方案 {i + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.label}
                className="border-b border-slate-200/60 last:border-0 dark:border-slate-800/60"
              >
                <td className="py-1.5 pr-3 font-medium text-slate-700 dark:text-slate-200">
                  {row.label}
                </td>
                {plans.map((p, i) => (
                  <td key={i} className="py-1.5 pr-3">
                    {row.render(p)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
