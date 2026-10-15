"use client";

import type { FlightLegOut, StrategyPlanOut } from "@/lib/types";

/**
 * SVG timeline: X 軸是日期，每張票一列，legs 畫為橫向色帶。
 * 四段票的兩次 TPE 交接會畫出垂直連接線。
 */
export function TimelineView({ plan }: { plan: StrategyPlanOut }) {
  const legs = plan.tickets.flatMap((t) =>
    t.legs.map((leg) => ({ leg, ticketId: t.offer_id }))
  );
  if (legs.length === 0) return null;

  const minTime = Math.min(...legs.map((l) => Date.parse(l.leg.departure)));
  const maxTime = Math.max(...legs.map((l) => Date.parse(l.leg.arrival)));
  const totalSpan = Math.max(maxTime - minTime, 1);
  const WIDTH = 640;
  const ROW_H = 32;
  const PAD_X = 24;

  const ticketColors = ["#0ea5e9", "#f59e0b"];
  const ticketIds = plan.tickets.map((t) => t.offer_id);

  const x = (t: number) =>
    PAD_X + ((t - minTime) / totalSpan) * (WIDTH - PAD_X * 2);

  const rows = plan.tickets.map((ticket, ti) => ({
    ti,
    ticket,
    y: 24 + ti * (ROW_H + 16),
    color: ticketColors[ti % ticketColors.length],
  }));

  const height = 24 + rows.length * (ROW_H + 16) + 24;

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${WIDTH} ${height}`}
        className="w-full text-slate-700 dark:text-slate-200"
        aria-label="Flight timeline"
      >
        {/* axis */}
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
          <g key={ticket.offer_id}>
            <text x={0} y={y + 20} fontSize={11} fill="currentColor" opacity={0.6}>
              {ti === 0 ? "票甲" : "票乙"}
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
                    y={y + 13}
                    fontSize={10}
                    fill="white"
                    fontWeight={600}
                  >
                    {leg.origin}→{leg.destination}
                  </text>
                  <text x={x1 + 4} y={y + 26} fontSize={9} fill="white" opacity={0.9}>
                    {leg.carrier}
                    {leg.flight_number.replace(/^[A-Z]+/, "")}
                  </text>
                </g>
              );
            })}
          </g>
        ))}

        {/* cross-ticket junction markers (hub = destination of leg N == origin of leg N+1 across tickets) */}
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
        紅色虛線 = 跨票交接點，需符合 MCT (建議緩衝 ≥ 3.5h)。
      </small>
    </div>
  );
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
  if (plan.tickets.length < 2) return [];
  const outer = plan.tickets[0];
  const inner = plan.tickets[1];
  if (!outer || !inner) return [];
  const marks: Junction[] = [];
  const addMid = (a: FlightLegOut, b: FlightLegOut, airport: string) => {
    const mid = (Date.parse(a.arrival) + Date.parse(b.departure)) / 2;
    marks.push({ x: x(mid), airport });
  };
  addMid(outer.legs[0], inner.legs[0], outer.legs[0].destination);
  if (outer.legs[1] && inner.legs[1]) {
    addMid(inner.legs[1], outer.legs[1], outer.legs[1].origin);
  }
  return marks;
}
