"use client";

import Link from "next/link";
import { useState } from "react";

import { ResultBoard } from "@/components/ResultBoard";
import { SearchForm } from "@/components/SearchForm";
import { ShortcutHelp } from "@/components/ShortcutHelp";
import type { SearchResult } from "@/lib/types";

export default function HomePage() {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

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
            查詢耗時 {elapsedMs} ms · 使用 stub provider (Phase 2 — 尚未串實體 API)
          </div>
          <ResultBoard result={result} />
        </div>
      )}

      <ShortcutHelp />
    </main>
  );
}
