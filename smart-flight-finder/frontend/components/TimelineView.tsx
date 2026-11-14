"use client";

import type { FlightLegOut, StrategyPlanOut } from "@/lib/types";

/**
 * SVG timeline: X 軸是日期，每張票一列，legs 畫為橫向色帶。
 * 跨票的交接點 (前一張票的最後 arrival 到下一張票的第一次 departure) 標為紅色虛線。
 * 支援 N 張票 (4-leg = 2 票, multi-city = N 段 = N 票)。
 */
export function TimelineView({ plan }: { plan: StrategyPlanOut }) {
  if (!plan.tickets.length) return null;
  const allLegs = plan.tickets.flatMap((t) => t.legs);
  if (allLegs.length === 0) return null;

  const minTime = Math.min(...allLegs.map((l) => Date.parse(l.departure)));
  const maxTime = Math.max(...allLegs.map((l) => Date.parse(l.arrival)));
  const totalSpan = Math.max(maxTime - minTime, 1);
  const WIDTH = 640;
  const ROW_H = 28;
  const PAD_X = 48;

  const ticketPalette = [
    "#0ea5e9", // sky
    "#f59e0b", // amber
    "#10b981", // emerald
    "#8b5cf6", // violet
    "#ef4444", // red
    "#64748b", // slate
  ];

  const x = (t: number) =>
    PAD_X + ((t - minTime) / totalSpan) * (WIDTH - PAD_X * 2);

  const rows = plan.tickets.map((ticket, ti) => ({
    ti,
    ticket,
    y: 24 + ti * (ROW_H + 10),
    color: ticketPalette[ti % ticketPalette.length],
  }));

  const height = 24 + rows.length * (ROW_H + 10) + 28;

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${WIDTH} ${height}`}
        className="w-full text-slate-700 dark:text-slate-200"
        aria-label="Flight timeline"
      >
        <line
          x1={PAD_X}
          x2={WIDTH - PAD_X}
          y1={height - 20}
          y2={height - 20}
          stroke="currentColor"
          strokeOpacity={0.3}
        />
        {axisTicks(minTime, maxTime).map((t) => (
          <g key={t} transform={`translate(${x(t)}, ${height - 20})`}>
            <line y1={0} y2={-6} stroke="currentColor" strokeOpacity={0.5} />
            <text
              y={14}
              textAnchor="middle"
              fontSize={10}
              fill="currentColor"
              opacity={0.6}
            >
              {formatDay(t)}
            </text>
          </g>
        ))}

        {rows.map(({ ti, ticket, y, color }) => (
          <g key={`${ticket.offer_id}-${ti}`}>
            <text x={0} y={y + 18} fontSize={11} fill="currentColor" opacity={0.6}>
              {rowLabel(plan.tickets.length, ti)}
            </text>
            {ticket.legs.map((leg, li) => {
              const x1 = x(Date.parse(leg.departure));
              const x2 = x(Date.parse(leg.arrival));
              return (
                <g key={li}>
                  <rect
                    x={x1}
                    y={y}
                    width={Math.max(x2 - x1, 2)}
                    height={ROW_H}
                    rx={4}
                    fill={color}
                    opacity={0.85}
                  />
                  <text
                    x={x1 + 4}
                    y={y + 12}
                    fontSize={10}
                    fill="white"
                    fontWeight={600}
                  >
                    {leg.origin}→{leg.destination}
                  </text>
                  <text x={x1 + 4} y={y + 23} fontSize={9} fill="white" opacity={0.9}>
                    {leg.flight_number}
                  </text>
                </g>
              );
            })}
          </g>
        ))}

        {junctionMarkers(plan, x).map((j, i) => (
          <g key={i}>
            <line
              x1={j.x}
              x2={j.x}
              y1={16}
              y2={height - 28}
              stroke="#ef4444"
              strokeDasharray="4,3"
              strokeOpacity={0.7}
            />
            <text
              x={j.x + 4}
              y={16}
              fontSize={10}
              fill="#ef4444"
              fontWeight={600}
            >
              交接 {j.airport}
            </text>
          </g>
        ))}
      </svg>
      <small className="text-xs text-slate-500">
        紅色虛線 = 跨票交接點。四段票建議 ≥ 3.5h 緩衝；multi-city 的跨段若在不同機場屬 open-jaw (無 MCT 風險)。
      </small>
    </div>
  );
}

function rowLabel(total: number, i: number): string {
  if (total === 2) return i === 0 ? "票甲" : "票乙";
  return `#${i + 1}`;
}

function axisTicks(min: number, max: number): number[] {
  const dayMs = 24 * 60 * 60 * 1000;
  const first = Math.ceil(min / dayMs) * dayMs;
  const ticks: number[] = [];
  for (let t = first; t <= max; t += dayMs) ticks.push(t);
  return ticks.length ? ticks : [min, max];
}

function formatDay(ts: number): string {
  const d = new Date(ts);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
}

type Junction = { x: number; airport: string };

function junctionMarkers(
  plan: StrategyPlanOut,
  x: (ts: number) => number
): Junction[] {
  const marks: Junction[] = [];
  for (let i = 0; i < plan.tickets.length - 1; i++) {
    const inbound = lastLeg(plan.tickets[i].legs);
    const outbound = firstLeg(plan.tickets[i + 1].legs);
    if (!inbound || !outbound) continue;
    // Only mark it as a 交接 when both ends sit on the same airport
    // (otherwise it's open-jaw with ground transit, not an MCT handoff).
    if (inbound.destination !== outbound.origin) continue;
    const mid = (Date.parse(inbound.arrival) + Date.parse(outbound.departure)) / 2;
    marks.push({ x: x(mid), airport: inbound.destination });
  }
  return marks;
}

function firstLeg(legs: FlightLegOut[]): FlightLegOut | undefined {
  return legs[0];
}

function lastLeg(legs: FlightLegOut[]): FlightLegOut | undefined {
  return legs[legs.length - 1];
}
