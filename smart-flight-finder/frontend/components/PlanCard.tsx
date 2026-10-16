"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { TimelineView } from "./TimelineView";
import type { RiskLevel, StrategyPlanOut, TicketStrategyType } from "@/lib/types";

const STRATEGY_LABEL: Record<TicketStrategyType, string> = {
  standard: "一般來回",
  open_jaw: "Open-jaw",
  reverse: "反向票",
  back_to_back_4leg: "外站四段票",
  hidden_city: "隱藏城市",
};

const RISK_BADGE: Record<RiskLevel, string> = {
  low: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  high: "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300",
};

export function PlanCard({ plan, rank }: { plan: StrategyPlanOut; rank: number }) {
  const [open, setOpen] = useState(rank === 1);
  const [downloading, setDownloading] = useState(false);
  const twd = plan.total_cost.toLocaleString("en-US");

  async function downloadIcs() {
    setDownloading(true);
    try {
      const blob = await api.planAsIcs(plan);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `flight-plan-${plan.strategy}.ics`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`匯出失敗：${(err as Error).message}`);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <article className="rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <header
        className="flex cursor-pointer items-center justify-between gap-3 px-4 py-3"
        onClick={() => setOpen((o) => !o)}
      >
        <div className="flex items-center gap-3">
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            #{rank}
          </span>
          <span className="rounded-full bg-brand/10 px-2 py-0.5 text-xs font-medium text-brand-dark dark:text-brand">
            {STRATEGY_LABEL[plan.strategy]}
          </span>
          <span className="text-sm text-slate-600 dark:text-slate-400">
            {plan.explain}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <div className="text-lg font-semibold">
              {plan.currency} {twd}
            </div>
            {plan.score !== null && (
              <div className="text-xs text-slate-500">
                score {plan.score.toFixed(3)}
              </div>
            )}
          </div>
          <button
            type="button"
            aria-label="Toggle details"
            className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            {open ? "收合" : "展開"}
          </button>
        </div>
      </header>

      {open && (
        <div className="space-y-4 border-t border-slate-200 px-4 py-4 dark:border-slate-800">
          <div className="flex justify-end">
            <button
              type="button"
              onClick={downloadIcs}
              disabled={downloading}
              className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800"
            >
              {downloading ? "匯出中…" : "加入日曆 (.ics)"}
            </button>
          </div>
          <TimelineView plan={plan} />

          <div className="grid gap-4 md:grid-cols-2">
            {plan.tickets.map((t, i) => (
              <section
                key={t.offer_id}
                className="rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800"
              >
                <h4 className="mb-2 font-semibold">
                  {plan.tickets.length === 2 ? (i === 0 ? "票甲 (外站)" : "票乙 (中段)") : "票"}
                  <span className="ml-2 font-mono text-xs text-slate-500">
                    {t.offer_id}
                  </span>
                </h4>
                <div className="text-xs text-slate-500">
                  {t.currency} {t.total_price.toLocaleString()} ·{" "}
                  {t.fare_class || "—"} ·{" "}
                  {t.baggage_through_checked ? "行李直掛" : "需提領重掛"}
                </div>
                <ul className="mt-2 space-y-1">
                  {t.legs.map((leg, li) => (
                    <li key={li} className="font-mono text-xs">
                      {leg.origin}→{leg.destination} · {leg.carrier}
                      {leg.flight_number} ·{" "}
                      {new Date(leg.departure).toISOString().slice(0, 16).replace("T", " ")}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>

          {plan.warnings.length > 0 && (
            <ul className="space-y-1">
              {plan.warnings.map((w) => (
                <li
                  key={`${w.code}-${w.message}`}
                  className={`inline-flex items-start gap-2 rounded px-2 py-1 text-xs ${RISK_BADGE[w.level]}`}
                >
                  <span className="uppercase font-semibold">{w.level}</span>
                  <span>{w.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </article>
  );
}
