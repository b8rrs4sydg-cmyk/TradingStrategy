"use client";

/**
 * localStorage-backed per-browser favorites.
 *
 * Keyed by a stable fingerprint of the plan (strategy + first offer id +
 * total cost + first leg timestamp) so re-running the same search won't
 * create duplicates. Fully optional — a browser with cleared/blocked storage
 * just gets an empty set, no app errors.
 */

import type { StrategyPlanOut } from "./types";

const STORAGE_KEY = "sff.favorites.v1";

export function fingerprintPlan(p: StrategyPlanOut): string {
  const first = p.tickets[0]?.legs[0];
  return [
    p.strategy,
    p.tickets[0]?.offer_id ?? "",
    p.total_cost,
    first ? first.departure : "",
    first ? `${first.origin}-${first.destination}` : "",
  ].join("|");
}

export function readFavorites(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((v) => typeof v === "string"));
  } catch {
    return new Set();
  }
}

export function writeFavorites(favs: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...favs]));
  } catch {
    /* storage disabled; favorites are per-session only */
  }
}

export function toggleFavorite(key: string): Set<string> {
  const favs = readFavorites();
  if (favs.has(key)) favs.delete(key);
  else favs.add(key);
  writeFavorites(favs);
  return favs;
}
