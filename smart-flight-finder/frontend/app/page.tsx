import { HolidayList } from "@/components/HolidayList";

export default function HomePage() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <header className="mb-8">
        <h1 className="text-3xl font-bold">Smart Flight Finder</h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400">
          以假期為核心，整合彈性日期矩陣、多段旅程、反向票與外站四段票策略。
          Phase 1 骨架 — 下方展示 2027 連假與請假攻略資料。
        </p>
      </header>

      <HolidayList />

      <section className="mt-12 rounded-lg border border-slate-200 dark:border-slate-800 p-5">
        <h2 className="text-xl font-semibold">Roadmap</h2>
        <ol className="mt-3 list-decimal space-y-1 pl-6 text-sm text-slate-700 dark:text-slate-300">
          <li>Phase 1 ✅ — 專案骨架、資料模型、2027 連假靜態 DB</li>
          <li>Phase 2 — 彈性日期矩陣 + Amadeus/Skyscanner 整合 + Redis 快取</li>
          <li>Phase 3 — 反向票 / 四段票策略引擎 (時間軸碰撞 + MCT 檢查)</li>
          <li>Phase 4 — 最佳化排序看板 + Timeline View</li>
          <li>Phase 5 — 壓測、調校、雲端部署</li>
        </ol>
      </section>
    </main>
  );
}
