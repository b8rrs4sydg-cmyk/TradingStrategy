"use client";

/**
 * Encode / decode a plan into a shareable URL hash.
 *
 * Format: ``#p=<base64url(JSON)>``. Everything travels in the hash so we
 * never leak sensitive data server-side (the Next.js runtime, Vercel edge,
 * and access logs all see only the path + query, not the fragment).
 *
 * Decoding is defensive: a malformed hash yields ``null`` rather than
 * throwing — the home page falls back to the normal search form.
 */

import type { StrategyPlanOut } from "./types";

const HASH_KEY = "p";

export function encodePlanToHash(plan: StrategyPlanOut): string {
  const json = JSON.stringify(plan);
  const bytes = new TextEncoder().encode(json);
  return `#${HASH_KEY}=${base64urlEncode(bytes)}`;
}

export function decodePlanFromHash(hash: string): StrategyPlanOut | null {
  if (!hash || hash.length < 3) return null;
  const trimmed = hash.startsWith("#") ? hash.slice(1) : hash;
  const prefix = `${HASH_KEY}=`;
  if (!trimmed.startsWith(prefix)) return null;
  try {
    const bytes = base64urlDecode(trimmed.slice(prefix.length));
    const json = new TextDecoder().decode(bytes);
    const parsed = JSON.parse(json);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof parsed.strategy === "string" &&
      Array.isArray(parsed.tickets)
    ) {
      return parsed as StrategyPlanOut;
    }
    return null;
  } catch {
    return null;
  }
}

export function sharePlanUrl(plan: StrategyPlanOut, origin?: string): string {
  const o =
    origin ?? (typeof window === "undefined" ? "" : `${window.location.origin}${window.location.pathname}`);
  return `${o}${encodePlanToHash(plan)}`;
}

function base64urlEncode(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  const b64 = typeof btoa === "undefined"
    ? Buffer.from(bytes).toString("base64")
    : btoa(bin);
  return b64.replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

function base64urlDecode(s: string): Uint8Array {
  const padded = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin =
    typeof atob === "undefined"
      ? Buffer.from(padded, "base64").toString("binary")
      : atob(padded);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
