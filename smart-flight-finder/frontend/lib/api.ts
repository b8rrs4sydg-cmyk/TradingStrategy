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

async function postRaw(path: string, body: unknown): Promise<Response> {
  return fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
}

export const api = {
  holidays: () => get<Holiday[]>("/holidays/2027"),
  leaveStrategies: () => get<LeaveStrategy[]>("/holidays/2027/leave-strategies"),
  search: (req: ItineraryRequestIn) => post<SearchResult>("/search", req),
  planAsIcs: async (plan: unknown): Promise<Blob> => {
    const res = await postRaw("/plans/ics", plan);
    if (!res.ok) throw new Error(`POST /plans/ics → ${res.status}`);
    return res.blob();
  },
  plansAsCsv: async (plans: unknown[]): Promise<Blob> => {
    const res = await postRaw("/plans/csv", { plans });
    if (!res.ok) throw new Error(`POST /plans/csv → ${res.status}`);
    return res.blob();
  },
};
