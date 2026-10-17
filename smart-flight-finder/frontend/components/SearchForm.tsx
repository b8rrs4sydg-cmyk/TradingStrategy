"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import type {
  CandidateWindowIn,
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

type Candidate = {
  id: number;
  label: string;
  holiday_key: string | null;
  depart: string;
  return_date: string;
  depart_flex: number;
  return_flex: number;
};

let nextCandidateId = 1;

function candidateFrom(s: LeaveStrategy, flex: number): Candidate {
  return {
    id: nextCandidateId++,
    label: "",
    holiday_key: s.holiday_key,
    depart: s.window_start,
    return_date: s.window_end,
    depart_flex: flex,
    return_flex: flex,
  };
}

const INITIAL_CANDIDATES: Candidate[] = [
  {
    id: nextCandidateId++,
    label: "",
    holiday_key: "lunar_ny",
    depart: "2027-02-05",
    return_date: "2027-02-15",
    depart_flex: 2,
    return_flex: 2,
  },
];

type Props = {
  onResult: (r: SearchResult, loadingMs: number) => void;
  onError: (err: Error) => void;
};

export function SearchForm({ onResult, onError }: Props) {
  const [strategies, setStrategies] = useState<LeaveStrategy[]>([]);
  const [tripType, setTripType] = useState<TripType>("round_trip");
  const [candidates, setCandidates] = useState<Candidate[]>(INITIAL_CANDIDATES);
  const [bulkFlex, setBulkFlex] = useState(2);
  const [origins, setOrigins] = useState("TPE");
  const [destinations, setDestinations] = useState("NRT, HND");
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
  const formRef = useRef<HTMLFormElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // ⌘/Ctrl + Enter submits from any field in the form
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        formRef.current?.requestSubmit();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    api.leaveStrategies()
      .then(setStrategies)
      .catch(() => {
        /* leave empty — form still usable with manual dates */
      });
  }, []);

  const selectedStrategies = useMemo(
    () =>
      (Object.entries(enabledStrategies)
        .filter(([, v]) => v)
        .map(([k]) => k) as TicketStrategyType[]),
    [enabledStrategies]
  );

  const isRoundTrip = tripType === "round_trip";
  const holidayByKey = useMemo(
    () => new Map(strategies.map((s) => [s.holiday_key, s])),
    [strategies]
  );
  const badCandidate = (c: Candidate) =>
    !c.depart || (isRoundTrip && (!c.return_date || c.return_date < c.depart));
  const candidatesInvalid =
    tripType !== "multi_city" && (candidates.length === 0 || candidates.some(badCandidate));
  const comboCount = candidates.reduce(
    (n, c) => n + (2 * c.depart_flex + 1) * (isRoundTrip ? 2 * c.return_flex + 1 : 1),
    0
  );

  function toggleHoliday(s: LeaveStrategy) {
    setCandidates((prev) =>
      prev.some((c) => c.holiday_key === s.holiday_key)
        ? prev.filter((c) => c.holiday_key !== s.holiday_key)
        : [...prev, candidateFrom(s, bulkFlex)]
    );
  }

  function updateCandidate(id: number, patch: Partial<Candidate>) {
    setCandidates((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  }

  function resetCandidate(c: Candidate) {
    const h = c.holiday_key ? holidayByKey.get(c.holiday_key) : undefined;
    if (h) updateCandidate(c.id, { depart: h.window_start, return_date: h.window_end });
  }

  function addCustomCandidate() {
    const last = candidates[candidates.length - 1];
    setCandidates((prev) => [
      ...prev,
      {
        id: nextCandidateId++,
        label: "",
        holiday_key: null,
        depart: last?.depart ?? "2027-02-05",
        return_date: last?.return_date ?? "2027-02-11",
        depart_flex: bulkFlex,
        return_flex: bulkFlex,
      },
    ]);
  }

  function applyBulkFlex() {
    setCandidates((prev) =>
      prev.map((c) => ({ ...c, depart_flex: bulkFlex, return_flex: bulkFlex }))
    );
  }

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
      const isMulti = tripType === "multi_city";
      const windows: DateWindowIn[] = isMulti
        ? segments.map((seg, i) => ({
            role: "segment",
            anchor_date: seg.anchor_date,
            flex_before: seg.flex,
            flex_after: seg.flex,
            sequence: i,
            segment_origin: seg.origin.trim().toUpperCase() || null,
            segment_destination: seg.destination.trim().toUpperCase() || null,
          }))
        : [];
      const candidateWindows: CandidateWindowIn[] = isMulti
        ? []
        : candidates.map((c) => ({
            label: c.label.trim() || null,
            holiday_key: c.holiday_key,
            depart: c.depart,
            return_date: isRoundTrip ? c.return_date : null,
            depart_flex: c.depart_flex,
            return_flex: c.return_flex,
          }));

      const req: ItineraryRequestIn = {
        trip_type: tripType,
        cabin: "economy",
        adults,
        children: 0,
        infants: 0,
        origins: origins.split(",").map((s) => s.trim()).filter(Boolean),
        destinations: destinations.split(",").map((s) => s.trim()).filter(Boolean),
        strategies: selectedStrategies.length ? selectedStrategies : ["standard"],
        holiday_key: null,
        candidate_windows: candidateWindows,
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
    <form
      ref={formRef}
      onSubmit={onSubmit}
      className="space-y-5 rounded-xl border border-slate-200 p-5 dark:border-slate-800"
    >
      <div className="grid gap-4 md:grid-cols-2">
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
      )}

      {!isMultiCity && (
        <fieldset className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
          <legend className="px-2 text-sm font-semibold">備選時段</legend>

          {strategies.length > 0 && (
            <div className="mb-4">
              <div className="mb-1 text-xs text-slate-500">
                2027 連假參考 — 點選加入 / 移除備選時段 (可多選)，加入後可再調整日期與彈性
              </div>
              <div className="flex flex-wrap gap-2">
                {strategies.map((h) => {
                  const on = candidates.some((c) => c.holiday_key === h.holiday_key);
                  return (
                    <button
                      key={h.holiday_key}
                      type="button"
                      onClick={() => toggleHoliday(h)}
                      aria-pressed={on}
                      title={h.description ?? undefined}
                      className={`rounded-full border px-3 py-1 text-xs ${
                        on
                          ? "border-brand bg-brand/10 text-brand-dark dark:text-brand"
                          : "border-slate-300 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                      }`}
                    >
                      {on ? "✓ " : "+ "}
                      {h.label_zh}
                      <span className="ml-1 font-mono text-[11px] opacity-70">
                        {h.window_start.slice(5)}→{h.window_end.slice(5)}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <ol className="space-y-3">
            {candidates.map((c) => {
              const h = c.holiday_key ? holidayByKey.get(c.holiday_key) : undefined;
              const bad = badCandidate(c);
              return (
                <li
                  key={c.id}
                  className={`grid gap-2 rounded-md border p-3 md:grid-cols-[1fr_auto_auto_auto] md:items-end ${
                    bad ? "border-rose-400" : "border-slate-200 dark:border-slate-800"
                  }`}
                >
                  <Field label={h ? `參考：${h.label_zh}` : "自訂時段"}>
                    <input
                      type="text"
                      value={c.label}
                      onChange={(e) => updateCandidate(c.id, { label: e.target.value })}
                      placeholder={h?.label_zh ?? "名稱 (選填)"}
                      maxLength={40}
                      className={fieldClass}
                    />
                  </Field>
                  <div className="grid grid-cols-[1fr_auto] gap-2">
                    <Field label="去程日">
                      <input
                        type="date"
                        value={c.depart}
                        onChange={(e) => updateCandidate(c.id, { depart: e.target.value })}
                        className={fieldClass}
                      />
                    </Field>
                    <Field label="± 天">
                      <FlexInput
                        value={c.depart_flex}
                        onChange={(v) => updateCandidate(c.id, { depart_flex: v })}
                      />
                    </Field>
                  </div>
                  {isRoundTrip ? (
                    <div className="grid grid-cols-[1fr_auto] gap-2">
                      <Field label="回程日">
                        <input
                          type="date"
                          value={c.return_date}
                          onChange={(e) => updateCandidate(c.id, { return_date: e.target.value })}
                          className={fieldClass}
                        />
                      </Field>
                      <Field label="± 天">
                        <FlexInput
                          value={c.return_flex}
                          onChange={(v) => updateCandidate(c.id, { return_flex: v })}
                        />
                      </Field>
                    </div>
                  ) : (
                    <div />
                  )}
                  <div className="flex gap-1 md:justify-end">
                    {h && (
                      <button
                        type="button"
                        onClick={() => resetCandidate(c)}
                        className={smallBtn}
                        title={`還原為 ${h.window_start} → ${h.window_end}`}
                      >
                        還原
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setCandidates((prev) => prev.filter((x) => x.id !== c.id))}
                      className={smallBtn}
                    >
                      移除
                    </button>
                  </div>
                  {bad && (
                    <p className="text-xs text-rose-600 md:col-span-4">
                      回程日需晚於或等於去程日
                    </p>
                  )}
                </li>
              );
            })}
          </ol>

          <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-slate-200 pt-3 text-xs dark:border-slate-800">
            <button type="button" onClick={addCustomCandidate} className={smallBtn}>
              + 自訂時段
            </button>
            <label className="flex items-center gap-2 whitespace-nowrap text-slate-600 dark:text-slate-300">
              彈性 ±
              <FlexInput value={bulkFlex} onChange={setBulkFlex} />天
            </label>
            <button
              type="button"
              onClick={applyBulkFlex}
              disabled={candidates.length === 0}
              className={smallBtn}
            >
              套用到全部時段
            </button>
            <span className="text-slate-500">
              {candidates.length === 0 ? (
                <span className="text-rose-600">請至少加入一個備選時段</span>
              ) : (
                <>
                  <strong>{candidates.length}</strong> 個時段 · 共{" "}
                  <strong>{comboCount}</strong> 組日期 × 每個勾選策略
                </>
              )}
            </span>
          </div>
        </fieldset>
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

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting || candidatesInvalid}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "搜尋中…" : "搜尋"}
        </button>
        <span className="text-xs text-slate-500">
          <kbd className="rounded border border-slate-300 bg-slate-100 px-1 font-mono dark:border-slate-700 dark:bg-slate-800">
            ⌘ Enter
          </kbd>{" "}
          從任何欄位送出
        </span>
      </div>
    </form>
  );
}

const fieldClass =
  "w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 shadow-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100";

const smallBtn =
  "rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800";

function FlexInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <input
      type="number"
      min={0}
      max={7}
      value={value}
      onChange={(e) => onChange(Math.max(0, Math.min(7, Number(e.target.value) || 0)))}
      className={fieldClass.replace("w-full", "w-16")}
    />
  );
}

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
