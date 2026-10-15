export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export type Holiday = {
  id: number;
  country: string;
  day: string; // ISO date
  name_zh: string;
  name_en: string;
  kind: string;
  is_workday: boolean;
  notes: string | null;
};

export type LeaveStrategy = {
  id: number;
  year: number;
  holiday_key: string;
  label_zh: string;
  pto_days: number;
  total_days: number;
  window_start: string;
  window_end: string;
  description: string | null;
};

export async function fetchHolidays(): Promise<Holiday[]> {
  const res = await fetch(`${API_BASE}/holidays/2027`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to fetch holidays: ${res.status}`);
  return res.json();
}

export async function fetchLeaveStrategies(): Promise<LeaveStrategy[]> {
  const res = await fetch(`${API_BASE}/holidays/2027/leave-strategies`, {
    cache: "no-store",
  });
  if (!res.ok)
    throw new Error(`Failed to fetch leave strategies: ${res.status}`);
  return res.json();
}
