"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { Holiday, LeaveStrategy } from "@/lib/types";

export default function HolidaysPage() {
  const [holidays, setHolidays] = useState<Holiday[] | null>(null);
  const [strategies, setStrategies] = useState<LeaveStrategy[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.holidays(), api.leaveStrategies()])
      .then(([h, s]) => {
        setHolidays(h);
        setStrategies(s);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">2027 台灣連假</h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            近似資料，正式上線前以 DGPA 公告為準。
          </p>
        </div>
        <nav className="text-sm">
          <Link
            href="/"
            className="rounded border border-slate-300 px-3 py-1 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            ← 回搜尋
          </Link>
        </nav>
      </header>

      {error && (
        <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200">
          無法連線 API：{error}
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <section>
          <h2 className="mb-3 text-lg font-semibold">官方假期</h2>
          <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {(holidays ?? []).map((h) => (
              <li
                key={h.id}
                className="flex items-center justify-between px-4 py-2 text-sm"
              >
                <span className="font-mono text-slate-500">{h.day}</span>
                <span className="font-medium">{h.name_zh}</span>
                <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {h.kind}
                </span>
              </li>
            ))}
            {holidays && holidays.length === 0 && (
              <li className="p-4 text-sm text-slate-500">尚無資料</li>
            )}
          </ul>
        </section>

        <section>
          <h2 className="mb-3 text-lg font-semibold">請假攻略</h2>
          <ul className="space-y-2">
            {(strategies ?? []).map((s) => (
              <li
                key={s.id}
                className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{s.label_zh}</span>
                  <span className="rounded-full bg-brand/10 px-2 py-0.5 text-xs text-brand-dark dark:text-brand">
                    請 {s.pto_days} / 休 {s.total_days}
                  </span>
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {s.window_start} → {s.window_end}
                </div>
                {s.description && (
                  <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
                    {s.description}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
