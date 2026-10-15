"use client";

import { useMemo, useState } from "react";

import { PlanCard } from "./PlanCard";
import type { SearchResult, StrategyPlanOut, TicketStrategyType } from "@/lib/types";

type SortKey = "score" | "price" | "pto";

export function ResultBoard({ result }: { result: SearchResult }) {
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [filterStrategy, setFilterStrategy] = useState<TicketStrategyType | "all">("all");

  const plans = useMemo(() => {
    let list = [...result.plans];
    if (filterStrategy !== "all") {
      list = list.filter((p) => p.strategy === filterStrategy);
    }
    switch (sortKey) {
      case "price":
        list.sort((a, b) => a.total_cost - b.total_cost);
        break;
      case "pto":
        list.sort((a, b) => (b.total_travel_days ?? 0) - (a.total_travel_days ?? 0));
        break;
      default:
        list.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
    }
    return list;
  }, [result.plans, sortKey, filterStrategy]);

  const strategyCounts = useMemo(() => {
    const map = new Map<TicketStrategyType, number>();
    for (const p of result.plans) {
      map.set(p.strategy, (map.get(p.strategy) ?? 0) + 1);
    }
    return map;
  }, [result.plans]);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 px-4 py-3 text-sm dark:border-slate-800">
        <div>
          <strong>{result.plans.length}</strong> 個方案 · 展開{" "}
          <strong>{result.date_matrix_size}</strong> 個日期組合
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2">
            <span className="text-xs text-slate-500">策略</span>
            <select
              value={filterStrategy}
              onChange={(e) => setFilterStrategy(e.target.value as TicketStrategyType | "all")}
              className="rounded border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-900"
            >
              <option value="all">全部 ({result.plans.length})</option>
              {Array.from(strategyCounts.entries()).map(([k, c]) => (
                <option key={k} value={k}>
                  {k} ({c})
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <span className="text-xs text-slate-500">排序</span>
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="rounded border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-900"
            >
              <option value="score">綜合分數</option>
              <option value="price">總價 (低→高)</option>
              <option value="pto">停留天數 (多→少)</option>
            </select>
          </label>
        </div>
      </div>

      <div className="space-y-3">
        {plans.map((plan, i) => (
          <PlanCard key={`${plan.strategy}-${i}-${plan.tickets[0]?.offer_id}`} plan={plan} rank={i + 1} />
        ))}
        {plans.length === 0 && (
          <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
            找不到符合條件的方案 — 試著調大日期彈性、放寬預算，或開啟更多策略。
          </div>
        )}
      </div>
    </section>
  );
}
