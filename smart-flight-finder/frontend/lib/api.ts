// All API calls go through the Next.js /api rewrite (next.config.js) so the
// code works identically from both the browser and the SSR runtime (inside
// Docker the proxy keeps "api:8000" out of the public URL).

import type {
  Holiday,
  ItineraryRequestIn,
  LeaveStrategy,
  SearchResult,
} from "./types";

export type { Holiday, LeaveStrategy } from "./types";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`POST ${path} → ${res.status} ${text}`);
  }
  return res.json();
}

export const api = {
  holidays: () => get<Holiday[]>("/holidays/2027"),
  leaveStrategies: () => get<LeaveStrategy[]>("/holidays/2027/leave-strategies"),
  search: (req: ItineraryRequestIn) => post<SearchResult>("/search", req),
};
