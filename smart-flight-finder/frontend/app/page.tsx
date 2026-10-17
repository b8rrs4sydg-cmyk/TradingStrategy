"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PlanCard } from "@/components/PlanCard";
import { ResultBoard } from "@/components/ResultBoard";
import { SearchForm } from "@/components/SearchForm";
import { ShortcutHelp } from "@/components/ShortcutHelp";
import { ThemeToggle } from "@/components/ThemeToggle";
import { decodePlanFromHash } from "@/lib/share";
import type { SearchResult, StrategyPlanOut } from "@/lib/types";

export default function HomePage() {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const [sharedPlan, setSharedPlan] = useState<StrategyPlanOut | null>(null);

  useEffect(() => {
    const plan = decodePlanFromHash(window.location.hash);
    if (plan) setSharedPlan(plan);
  }, []);

  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Smart Flight Finder</h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            以假期為核心：彈性日期矩陣 × 多段旅程 × 反向票 / 外站四段票。
          </p>
        </div>
        <nav className="text-sm">
          <Link
            href="/holidays"
            className="rounded border border-slate-300 px-3 py-1 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            2027 連假 →
          </Link>
        </nav>
      </header>

      {sharedPlan && (
        <section className="mb-8 space-y-3 rounded-xl border border-brand/40 bg-brand/5 p-4 dark:bg-brand/10">
          <header className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">分享的方案</h2>
            <button
              type="button"
              onClick={() => {
                setSharedPlan(null);
                history.replaceState(null, "", window.location.pathname);
              }}
              className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              關閉
            </button>
          </header>
          <PlanCard plan={sharedPlan} rank={1} />
        </section>
      )}

      <SearchForm
        onResult={(r, ms) => {
          setResult(r);
          setElapsedMs(ms);
          setError(null);
        }}
        onError={(err) => setError(err.message)}
      />

      {error && (
        <div className="mt-6 rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-900 dark:border-rose-700 dark:bg-rose-950/30 dark:text-rose-200">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-10 space-y-3">
          <div className="text-xs text-slate-500">
            查詢耗時 {elapsedMs} ms · 票價來源：Google Flights 實價資料庫（每 6 小時爬取）
          </div>
          <ResultBoard result={result} />
        </div>
      )}

      <ThemeToggle />
      <ShortcutHelp />
    </main>
  );
}
