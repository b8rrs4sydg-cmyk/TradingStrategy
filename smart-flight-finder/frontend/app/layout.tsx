import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Smart Flight Finder",
  description:
    "智慧化進階機票搜尋與策略規劃系統 — 連假、彈性日期、反向票、四段票",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-Hant">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
