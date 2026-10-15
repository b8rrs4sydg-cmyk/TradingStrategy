import { fetchHolidays, fetchLeaveStrategies } from "@/lib/api";

export async function HolidayList() {
  let holidays, strategies;
  try {
    [holidays, strategies] = await Promise.all([
      fetchHolidays(),
      fetchLeaveStrategies(),
    ]);
  } catch (err) {
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200">
        無法連線到 API：{(err as Error).message}
        <br />
        請確認後端已啟動 (<code>docker compose up api</code> 或{" "}
        <code>uvicorn app.main:app --reload</code>)。
      </div>
    );
  }

  return (
    <div className="grid gap-6 md:grid-cols-2">
      <section>
        <h2 className="mb-3 text-lg font-semibold">2027 台灣連假</h2>
        <ul className="divide-y divide-slate-200 rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {holidays.map((h) => (
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
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold">2027 請假攻略</h2>
        <ul className="space-y-2">
          {strategies.map((s) => (
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
  );
}
