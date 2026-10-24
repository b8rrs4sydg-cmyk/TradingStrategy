"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { fingerprintPlan, readFavorites } from "@/lib/favorites";
import { ComparePanel } from "./ComparePanel";
import { MatrixHeatmap } from "./MatrixHeatmap";
import { PlanCard } from "./PlanCard";
import type { SearchResult, StrategyPlanOut, TicketStrategyType } from "@/lib/types";

type SortKey = "score" | "price" | "pto";

const MAX_COMPARE = 4;

export function ResultBoard({ result }: { result: SearchResult }) {
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [filterStrategy, setFilterStrategy] = useState<TicketStrategyType | "all">("all");
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [comparing, setComparing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [favorites, setFavorites] = useState<Set<string>>(new Set());

  useEffect(() => {
    setFavorites(readFavorites());
  }, [result]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && comparing) {
        setComparing(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [comparing]);

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
    // Favorites rise to the top within whatever sort order the user picked.
    list.sort(
      (a, b) =>
        (favorites.has(fingerprintPlan(b)) ? 1 : 0) -
        (favorites.has(fingerprintPlan(a)) ? 1 : 0),
    );
    return list;
  }, [result.plans, sortKey, filterStrategy, favorites]);

  const strategyCounts = useMemo(() => {
    const map = new Map<TicketStrategyType, number>();
    for (const p of result.plans) {
      map.set(p.strategy, (map.get(p.strategy) ?? 0) + 1);
    }
    return map;
  }, [result.plans]);

  const cache = result.provider_cache;
  const hitRate =
    cache && cache.total ? (cache.hits ?? 0) / cache.total : null;

  function keyOf(plan: StrategyPlanOut, idx: number): string {
    return `${plan.strategy}-${idx}-${plan.tickets[0]?.offer_id ?? ""}`;
  }

  function toggle(key: string) {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else if (next.size < MAX_COMPARE) {
        next.add(key);
      }
      return next;
    });
  }

  const selectedPlans = useMemo(
    () => plans.filter((p, i) => selectedKeys.has(keyOf(p, i))),
    [plans, selectedKeys],
  );

  async function downloadCsv() {
    setExporting(true);
    try {
      const payload = selectedPlans.length ? selectedPlans : plans;
      const blob = await api.plansAsCsv(payload);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "flight-plans.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`匯出失敗：${(err as Error).message}`);
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 px-4 py-3 text-sm dark:border-slate-800">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span>
            <strong>{result.plans.length}</strong> 個方案 · 展開{" "}
            <strong>{result.date_matrix_size}</strong> 個日期組合
          </span>
          {cache && cache.total ? (
            <span
              className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-200"
              title={`${cache.unique_queries ?? 0} unique queries → ${cache.total} total provider calls`}
            >
              Cache {hitRate !== null ? `${Math.round(hitRate * 100)}%` : "—"} ·
              {" "}省 {Math.max(0, cache.hits ?? 0)} 次 provider 呼叫
            </span>
          ) : null}
          {selectedPlans.length > 0 ? (
            <span className="rounded-full bg-brand/10 px-2 py-0.5 text-xs text-brand-dark dark:text-brand">
              已選 {selectedPlans.length} / {MAX_COMPARE}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setComparing((c) => !c)}
            disabled={selectedPlans.length < 2}
            className="rounded border border-brand px-2 py-1 text-xs text-brand hover:bg-brand/5 disabled:cursor-not-allowed disabled:border-slate-300 disabled:text-slate-400 dark:disabled:border-slate-700"
          >
            {comparing ? "關閉比較" : `比較 (${selectedPlans.length})`}
          </button>
          <button
            type="button"
            onClick={downloadCsv}
            disabled={exporting}
            className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800"
            title={selectedPlans.length ? "匯出已選" : "匯出全部"}
          >
            {exporting ? "匯出中…" : selectedPlans.length ? "CSV (已選)" : "CSV (全部)"}
          </button>
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

      {comparing && selectedPlans.length >= 2 && (
        <ComparePanel plans={selectedPlans} onClose={() => setComparing(false)} />
      )}

      {result.notices?.map((n) => (
        <p
          key={n}
          className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-200"
        >
          {n}
        </p>
      ))}

      {/* Two-trip plans span months; the outbound×return grid is per single trip. */}
      <MatrixHeatmap plans={result.plans.filter((p) => !p.trips?.length)} />

      <div className="space-y-3">
        {plans.map((plan, i) => {
          const k = keyOf(plan, i);
          const favKey = fingerprintPlan(plan);
          const checked = selectedKeys.has(k);
          const atLimit = !checked && selectedKeys.size >= MAX_COMPARE;
          return (
            <div key={k} className="flex items-start gap-2">
              <input
                type="checkbox"
                className="mt-5 shrink-0"
                checked={checked}
                disabled={atLimit}
                onChange={() => toggle(k)}
                aria-label={`選擇方案 ${i + 1} 比較`}
              />
              <div className="flex-1">
                <PlanCard
                  plan={plan}
                  rank={i + 1}
                  isFavorite={favorites.has(favKey)}
                  onToggleFavorite={(key, next) =>
                    setFavorites((prev) => {
                      const copy = new Set(prev);
                      if (next) copy.add(key);
                      else copy.delete(key);
                      return copy;
                    })
                  }
                />
              </div>
            </div>
          );
        })}
        {plans.length === 0 && (
          <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
            找不到符合條件的方案 — 試著調大日期彈性、放寬預算，或開啟更多策略。
          </div>
        )}
      </div>
    </section>
  );
}
