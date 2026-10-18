"use client";

import { useEffect, useState } from "react";

const SHORTCUTS: Array<[string, string]> = [
  ["⌘/Ctrl + Enter", "從任何欄位送出搜尋"],
  ["?", "開啟 / 關閉這個說明"],
  ["Esc", "關閉比較面板或對話框"],
  ["☆ → ★ (按卡片星號)", "收藏方案，自動置頂"],
  ["□ (卡片左側 checkbox)", "選擇最多 4 個方案進入比較"],
];

export function ShortcutHelp() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement) {
        // Don't trigger the help modal while the user is typing a "?"
        // into a text input or textarea.
        const tag = e.target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable) return;
      }
      if (e.key === "?") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <button
        type="button"
        aria-label="鍵盤快捷鍵說明"
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-4 right-4 z-40 rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-600 shadow hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
      >
        ? 快捷鍵
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="鍵盤快捷鍵說明"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-5 shadow-lg dark:border-slate-700 dark:bg-slate-900"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold">鍵盤快捷鍵</h2>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                aria-label="關閉"
              >
                Esc
              </button>
            </header>
            <ul className="space-y-2 text-sm">
              {SHORTCUTS.map(([k, label]) => (
                <li
                  key={k}
                  className="flex items-start justify-between gap-4 border-b border-slate-100 pb-1 last:border-0 dark:border-slate-800"
                >
                  <span className="text-slate-700 dark:text-slate-300">{label}</span>
                  <kbd className="shrink-0 rounded border border-slate-300 bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
                    {k}
                  </kbd>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </>
  );
}
