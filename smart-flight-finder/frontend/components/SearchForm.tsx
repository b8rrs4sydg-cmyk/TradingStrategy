"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type {
  DateWindowIn,
  ItineraryRequestIn,
  LeaveStrategy,
  ScoringWeights,
  SearchResult,
  TicketStrategyType,
  TripType,
} from "@/lib/types";

const DEFAULT_WEIGHTS: ScoringWeights = {
  price: 0.5,
  pto_efficiency: 0.2,
  flight_time: 0.15,
  strategy_risk: 0.15,
};

type Segment = {
  origin: string;
  destination: string;
  anchor_date: string;
  flex: number;
};

const INITIAL_SEGMENTS: Segment[] = [
  { origin: "TPE", destination: "NRT", anchor_date: "2027-02-05", flex: 1 },
  { origin: "KIX", destination: "TPE", anchor_date: "2027-02-11", flex: 1 },
];

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
  const [segments, setSegments] = useState<Segment[]>(INITIAL_SEGMENTS);

  const [enabledStrategies, setEnabledStrategies] = useState<Record<TicketStrategyType, boolean>>({
    standard: true,
    open_jaw: false,
    reverse: true,
    back_to_back_4leg: false,
    hidden_city: false,
  });
  const [outerStations, setOuterStations] = useState("XMN");
  const [outerBufferDays, setOuterBufferDays] = useState(2);
  const [weights, setWeights] = useState<ScoringWeights>(DEFAULT_WEIGHTS);
  const [weightsOpen, setWeightsOpen] = useState(false);

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

  function updateSegment(i: number, patch: Partial<Segment>) {
    setSegments((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  }

  function addSegment() {
    const last = segments[segments.length - 1];
    setSegments((prev) => [
      ...prev,
      {
        origin: last?.destination ?? "TPE",
        destination: "TPE",
        anchor_date: last?.anchor_date ?? "2027-02-05",
        flex: 1,
      },
    ]);
  }

  function removeSegment(i: number) {
    setSegments((prev) => (prev.length <= 2 ? prev : prev.filter((_, idx) => idx !== i)));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    const startedAt = Date.now();
    try {
      const windows: DateWindowIn[] =
        tripType === "multi_city"
          ? segments.map((seg, i) => ({
              role: "segment",
              anchor_date: seg.anchor_date,
              flex_before: seg.flex,
              flex_after: seg.flex,
              sequence: i,
              segment_origin: seg.origin.trim().toUpperCase() || null,
              segment_destination: seg.destination.trim().toUpperCase() || null,
            }))
          : (() => {
              const w: DateWindowIn[] = [
                {
                  role: "outbound",
                  anchor_date: outbound,
                  flex_before: flexBefore,
                  flex_after: flexAfter,
                },
              ];
              if (tripType === "round_trip") {
                w.push({
                  role: "return",
                  anchor_date: returnDate,
                  flex_before: flexBefore,
                  flex_after: flexAfter,
                });
              }
              return w;
            })();

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
        scoring_weights: weights,
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
  const isMultiCity = tripType === "multi_city";

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

      {!isMultiCity && (
        <>
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
        </>
      )}

      {isMultiCity && (
        <fieldset className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
          <legend className="px-2 text-sm font-semibold">多段旅程</legend>
          <ol className="space-y-3">
            {segments.map((seg, i) => (
              <li
                key={i}
                className="grid gap-2 md:grid-cols-[auto_1fr_1fr_1fr_1fr_auto] md:items-end"
              >
                <span className="text-xs text-slate-500 md:self-center">#{i + 1}</span>
                <Field label="起點">
                  <input
                    type="text"
                    value={seg.origin}
                    onChange={(e) => updateSegment(i, { origin: e.target.value })}
                    placeholder="TPE"
                    className={fieldClass}
                  />
                </Field>
                <Field label="終點">
                  <input
                    type="text"
                    value={seg.destination}
                    onChange={(e) => updateSegment(i, { destination: e.target.value })}
                    placeholder="NRT"
                    className={fieldClass}
                  />
                </Field>
                <Field label="日期">
                  <input
                    type="date"
                    value={seg.anchor_date}
                    onChange={(e) => updateSegment(i, { anchor_date: e.target.value })}
                    className={fieldClass}
                  />
                </Field>
                <Field label={`彈性 ±${seg.flex} 天`}>
                  <input
                    type="range"
                    min={0}
                    max={7}
                    value={seg.flex}
                    onChange={(e) => updateSegment(i, { flex: Number(e.target.value) })}
                  />
                </Field>
                <button
                  type="button"
                  onClick={() => removeSegment(i)}
                  disabled={segments.length <= 2}
                  aria-label="移除本段"
                  className="justify-self-end rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  移除
                </button>
              </li>
            ))}
          </ol>
          <button
            type="button"
            onClick={addSegment}
            className="mt-3 rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            + 新增一段
          </button>
          <p className="mt-2 text-xs text-slate-500">
            Multi-city 需 ≥ 2 段，日期必須嚴格遞增。相鄰段的終點與下一段起點不同時代表 open-jaw。
          </p>
        </fieldset>
      )}

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

      <fieldset className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
        <legend className="px-2 text-sm font-semibold">
          <button
            type="button"
            onClick={() => setWeightsOpen((o) => !o)}
            className="text-sm font-semibold hover:underline"
          >
            {weightsOpen ? "▾" : "▸"} 評分權重 (進階)
          </button>
        </legend>
        {weightsOpen && (
          <div className="grid gap-3 md:grid-cols-2">
            <WeightSlider
              label="價格優先"
              value={weights.price}
              onChange={(v) => setWeights((w) => ({ ...w, price: v }))}
            />
            <WeightSlider
              label="請假效益比"
              value={weights.pto_efficiency}
              onChange={(v) => setWeights((w) => ({ ...w, pto_efficiency: v }))}
            />
            <WeightSlider
              label="飛行時長"
              value={weights.flight_time}
              onChange={(v) => setWeights((w) => ({ ...w, flight_time: v }))}
            />
            <WeightSlider
              label="策略風險 (低風險加分)"
              value={weights.strategy_risk}
              onChange={(v) => setWeights((w) => ({ ...w, strategy_risk: v }))}
            />
            <button
              type="button"
              onClick={() => setWeights(DEFAULT_WEIGHTS)}
              className="col-span-full mt-1 self-start text-xs text-slate-500 hover:underline"
            >
              重設為預設
            </button>
          </div>
        )}
      </fieldset>

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

function WeightSlider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-center justify-between text-xs font-medium uppercase tracking-wide text-slate-500">
        <span>{label}</span>
        <span className="font-mono text-slate-600 dark:text-slate-300">
          {value.toFixed(2)}
        </span>
      </span>
      <input
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
    </label>
  );
}
