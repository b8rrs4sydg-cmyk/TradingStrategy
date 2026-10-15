"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type {
  DateWindowIn,
  ItineraryRequestIn,
  LeaveStrategy,
  SearchResult,
  TicketStrategyType,
  TripType,
} from "@/lib/types";

const DEFAULT_WEIGHTS = {
  price: 0.5,
  pto_efficiency: 0.2,
  flight_time: 0.15,
  strategy_risk: 0.15,
};

type Props = {
  onResult: (r: SearchResult, loadingMs: number) => void;
  onError: (err: Error) => void;
};

export function SearchForm({ onResult, onError }: Props) {
  const [strategies, setStrategies] = useState<LeaveStrategy[]>([]);
  const [tripType, setTripType] = useState<TripType>("round_trip");
  const [holidayKey, setHolidayKey] = useState<string>("lunar_ny");
  const [origins, setOrigins] = useState("TPE");
  const [destinations, setDestinations] = useState("NRT, HND");
  const [outbound, setOutbound] = useState("2027-02-05");
  const [returnDate, setReturnDate] = useState("2027-02-11");
  const [flexBefore, setFlexBefore] = useState(2);
  const [flexAfter, setFlexAfter] = useState(2);
  const [adults, setAdults] = useState(1);
  const [budget, setBudget] = useState<string>("");

  const [enabledStrategies, setEnabledStrategies] = useState<Record<TicketStrategyType, boolean>>({
    standard: true,
    open_jaw: false,
    reverse: true,
    back_to_back_4leg: false,
    hidden_city: false,
  });
  const [outerStations, setOuterStations] = useState("XMN");
  const [outerBufferDays, setOuterBufferDays] = useState(2);

  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.leaveStrategies()
      .then(setStrategies)
      .catch(() => {
        /* leave empty — form still usable with manual dates */
      });
  }, []);

  // When the user picks a holiday, prefill the anchor dates to that
  // strategy's window edges so the search starts from a sensible place.
  useEffect(() => {
    const match = strategies.find((s) => s.holiday_key === holidayKey);
    if (match) {
      setOutbound(match.window_start);
      setReturnDate(match.window_end);
    }
  }, [holidayKey, strategies]);

  const selectedStrategies = useMemo(
    () =>
      (Object.entries(enabledStrategies)
        .filter(([, v]) => v)
        .map(([k]) => k) as TicketStrategyType[]),
    [enabledStrategies]
  );

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    const startedAt = Date.now();
    try {
      const windows: DateWindowIn[] = [
        {
          role: "outbound",
          anchor_date: outbound,
          flex_before: flexBefore,
          flex_after: flexAfter,
        },
      ];
      if (tripType === "round_trip") {
        windows.push({
          role: "return",
          anchor_date: returnDate,
          flex_before: flexBefore,
          flex_after: flexAfter,
        });
      }
      const req: ItineraryRequestIn = {
        trip_type: tripType,
        cabin: "economy",
        adults,
        children: 0,
        infants: 0,
        origins: origins.split(",").map((s) => s.trim()).filter(Boolean),
        destinations: destinations.split(",").map((s) => s.trim()).filter(Boolean),
        strategies: selectedStrategies.length ? selectedStrategies : ["standard"],
        holiday_key: holidayKey || null,
        max_total_budget: budget ? Number(budget) : null,
        max_pto_days: null,
        scoring_weights: DEFAULT_WEIGHTS,
        date_windows: windows,
        back_to_back_outer_stations: outerStations
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        back_to_back_outer_buffer_days: outerBufferDays,
      };
      const result = await api.search(req);
      onResult(result, Date.now() - startedAt);
    } catch (err) {
      onError(err as Error);
    } finally {
      setSubmitting(false);
    }
  }

  const fourLegOn = enabledStrategies.back_to_back_4leg;

  return (
    <form onSubmit={onSubmit} className="space-y-5 rounded-xl border border-slate-200 p-5 dark:border-slate-800">
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="假期快選">
          <select
            value={holidayKey}
            onChange={(e) => setHolidayKey(e.target.value)}
            className={fieldClass}
          >
            <option value="">— 自定義 —</option>
            {strategies.map((s) => (
              <option key={s.id} value={s.holiday_key}>
                {s.label_zh}
              </option>
            ))}
          </select>
        </Field>

        <Field label="行程類型">
          <select
            value={tripType}
            onChange={(e) => setTripType(e.target.value as TripType)}
            className={fieldClass}
          >
            <option value="round_trip">來回</option>
            <option value="one_way">單程</option>
            <option value="multi_city">多段 (Multi-city)</option>
          </select>
        </Field>

        <Field label="大人數">
          <input
            type="number"
            min={1}
            max={9}
            value={adults}
            onChange={(e) => setAdults(Number(e.target.value) || 1)}
            className={fieldClass}
          />
        </Field>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Field label="出發機場 (以逗號分隔)">
          <input
            type="text"
            value={origins}
            onChange={(e) => setOrigins(e.target.value)}
            placeholder="TPE, TSA, KHH"
            className={fieldClass}
          />
        </Field>
        <Field label="目的地 (IATA 或國碼)">
          <input
            type="text"
            value={destinations}
            onChange={(e) => setDestinations(e.target.value)}
            placeholder="NRT, HND, KIX"
            className={fieldClass}
          />
        </Field>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Field label="去程日">
          <input
            type="date"
            value={outbound}
            onChange={(e) => setOutbound(e.target.value)}
            className={fieldClass}
          />
        </Field>
        {tripType === "round_trip" && (
          <Field label="回程日">
            <input
              type="date"
              value={returnDate}
              onChange={(e) => setReturnDate(e.target.value)}
              className={fieldClass}
            />
          </Field>
        )}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Field label={`去/回程前彈性 ±${flexBefore} 天`}>
          <input
            type="range"
            min={0}
            max={7}
            value={flexBefore}
            onChange={(e) => setFlexBefore(Number(e.target.value))}
          />
        </Field>
        <Field label={`去/回程後彈性 ±${flexAfter} 天`}>
          <input
            type="range"
            min={0}
            max={7}
            value={flexAfter}
            onChange={(e) => setFlexAfter(Number(e.target.value))}
          />
        </Field>
      </div>

      <fieldset className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
        <legend className="px-2 text-sm font-semibold">策略</legend>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
          {(
            [
              ["standard", "一般來回 / 直購"],
              ["reverse", "反向票 (A-B-A vs B-A-B)"],
              ["back_to_back_4leg", "外站四段票"],
              ["open_jaw", "Open-jaw (開放式)"],
              ["hidden_city", "隱藏城市 (Skiplag)"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enabledStrategies[key]}
                onChange={(e) =>
                  setEnabledStrategies((s) => ({ ...s, [key]: e.target.checked }))
                }
              />
              {label}
            </label>
          ))}
        </div>

        {fourLegOn && (
          <div className="mt-4 grid gap-3 md:grid-cols-2 border-t border-slate-200 pt-4 dark:border-slate-800">
            <Field label="四段票：外站 (XMN, HKG, ICN ...)">
              <input
                type="text"
                value={outerStations}
                onChange={(e) => setOuterStations(e.target.value)}
                className={fieldClass}
              />
            </Field>
            <Field label={`外站緩衝 ±${outerBufferDays} 天`}>
              <input
                type="range"
                min={0}
                max={7}
                value={outerBufferDays}
                onChange={(e) => setOuterBufferDays(Number(e.target.value))}
              />
            </Field>
          </div>
        )}
      </fieldset>

      <div className="grid gap-4 md:grid-cols-2">
        <Field label="預算上限 (TWD)">
          <input
            type="number"
            min={0}
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="例如 60000"
            className={fieldClass}
          />
        </Field>
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "搜尋中…" : "搜尋"}
      </button>
    </form>
  );
}

const fieldClass =
  "w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 shadow-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      {children}
    </label>
  );
}
