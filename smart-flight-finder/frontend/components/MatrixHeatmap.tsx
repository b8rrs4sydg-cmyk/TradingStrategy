"use client";

import { useMemo } from "react";

import type { StrategyPlanOut } from "@/lib/types";

/**
 * Price heatmap over the outbound × return date matrix.
 *
 * The matrix is derived from the plans themselves — for each plan with ≥ 2
 * legs we take the first leg's departure day as "outbound" and the last
 * leg's departure day as "return". Cells show the min total_cost across all
 * plans landing on that (outbound, return) pair; empty cells render blank.
 *
 * Colors use a single-hue sequential scale (sky-50 → sky-700) so the eye
 * reads "lighter = cheaper, darker = pricier" without a legend.
 */
export function MatrixHeatmap({ plans }: { plans: StrategyPlanOut[] }) {
  const { outboundDays, returnDays, matrix, min, max } = useMemo(
    () => buildMatrix(plans),
    [plans],
  );

  if (outboundDays.length === 0 || returnDays.length === 0) return null;
  if (outboundDays.length === 1 && returnDays.length === 1) return null;

  return (
    <section className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">價格矩陣 (去程 × 回程)</h3>
        <span className="text-xs text-slate-500">
          每格 = 該日期組合下的最低總價 · 淺 → 深 代表便宜 → 貴
        </span>
      </header>
      <div className="overflow-x-auto">
        <table className="min-w-full border-separate border-spacing-0 text-xs">
          <thead>
            <tr>
              <th className="sticky left-0 bg-white px-2 py-1 text-left text-slate-400 dark:bg-slate-900">
                去程 ↓ / 回程 →
              </th>
              {returnDays.map((d) => (
                <th
                  key={d}
                  className="px-2 py-1 text-right font-mono text-slate-500"
                >
                  {fmtDay(d)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {outboundDays.map((out) => (
              <tr key={out}>
                <td className="sticky left-0 bg-white px-2 py-1 font-mono text-slate-500 dark:bg-slate-900">
                  {fmtDay(out)}
                </td>
                {returnDays.map((ret) => {
                  const price = matrix.get(`${out}|${ret}`);
                  return (
                    <td
                      key={ret}
                      className="px-2 py-1 text-right align-middle"
                      style={cellStyle(price, min, max)}
                      title={
                        price === undefined
                          ? "無資料"
                          : `${out} → ${ret}: ${price.toLocaleString()}`
                      }
                    >
                      {price === undefined ? "—" : (price / 1000).toFixed(1) + "k"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function buildMatrix(plans: StrategyPlanOut[]) {
  const matrix = new Map<string, number>();
  const outSet = new Set<string>();
  const retSet = new Set<string>();
  let min = Infinity;
  let max = -Infinity;

  for (const p of plans) {
    const first = p.tickets[0]?.legs[0];
    const lastTicket = p.tickets[p.tickets.length - 1];
    const last = lastTicket?.legs[lastTicket.legs.length - 1];
    if (!first || !last) continue;
    const out = first.departure.slice(0, 10);
    const ret = last.departure.slice(0, 10);
    if (out >= ret) continue; // one-ways or malformed
    const key = `${out}|${ret}`;
    const prev = matrix.get(key);
    if (prev === undefined || p.total_cost < prev) {
      matrix.set(key, p.total_cost);
    }
    outSet.add(out);
    retSet.add(ret);
    min = Math.min(min, p.total_cost);
    max = Math.max(max, p.total_cost);
  }

  return {
    outboundDays: [...outSet].sort(),
    returnDays: [...retSet].sort(),
    matrix,
    min,
    max,
  };
}

function cellStyle(
  price: number | undefined,
  min: number,
  max: number,
): React.CSSProperties {
  if (price === undefined || max === min) return {};
  const t = (price - min) / (max - min);
  // Sky scale: light at t=0, deep at t=1.
  const bg = `hsl(199, 89%, ${Math.round(94 - 60 * t)}%)`;
  const color = t > 0.55 ? "white" : "rgb(15 23 42)";
  return { backgroundColor: bg, color };
}

function fmtDay(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${m}/${d}`;
}
