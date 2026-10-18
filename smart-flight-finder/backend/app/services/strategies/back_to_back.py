"""外站四腿票 (四段票) — ONE ticket X→TPE→D→TPE→Y stitching THREE trips together.

The ticket is sold from an outstation X (a cheaper market than Taiwan). Its
first segment must be flown, so it is the *return* of a trip to X that you buy
separately, and its legs 2-3 / leg 4 belong to the next trips:

    旅程 1 (slot P):  單買初段 TPE→X (p_dep) … stay in X, any length …
                      leg1 X→TPE (c1, inside P's window)
    旅程 2 (slot Q):  leg2 TPE→D (c2) … D … leg3 D→TPE (q_ret)
    旅程 3 (slot R):  leg4 TPE→Y (r_dep) … Y … 單買最後一段 Y→TPE (r_ret)

Leg 1 must not be glued to leg 2 — they are the end of one trip and the start
of another, in different holidays. The 單買初段 / 最後一段 can instead be the
last/first leg of neighbouring 四腿票 — chaining tickets this way is the 循環.

頭尾不同國家: X, D and Y are pairwise in different countries so the trips never
revisit the same country. Either end can move: the planner tries every (X, Y)
pair of the chosen outstations. Such an origin open jaw is priced by Google
Flights as one multi-city ticket; airline rules on it vary, hence a warning.
Each plan prices the closed loop against three ordinary round trips (to X on
P, to D on Q, to Y on R); if no combination saves money, the cheapest one is
still returned, flagged ``no_saving``, so the real comparison stays visible.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import product

from app.data.airports import BY_CODE, TW_AIRPORT_CODES
from app.models.enums import TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.services.mct import DEFAULT_MCT, MctPolicy
from app.services.strategies.base import RiskLevel, RiskWarning, StrategyPlan, TicketOffer
from app.services.strategies.two_trip import (
    TripSlot,
    cheapest,
    fmt_day,
    nearest,
    quote,
    saving_warning,
)

HUB = "TPE"
_MAX_DATES_PER_LEG = 5  # multi-city quotes are expensive on real APIs


def _name(code: str) -> str:
    return BY_CODE[code].name_zh if code in BY_CODE else code


def _country(code: str) -> str:
    return BY_CODE[code].country if code in BY_CODE else code


class FourLegPlanner:
    strategy = TicketStrategyType.BACK_TO_BACK_4LEG

    def __init__(self, provider: FlightOfferProvider, *, mct: MctPolicy = DEFAULT_MCT) -> None:
        self.provider = provider
        self.mct = mct

    def plan(
        self,
        *,
        trip_p: TripSlot,
        trip_q: TripSlot,
        trip_r: TripSlot,
        outer_stations: Sequence[str],
        destinations: Sequence[str],
        adults: int = 1,
    ) -> list[StrategyPlan]:
        p_deps = nearest(trip_p.departs, _MAX_DATES_PER_LEG)
        c1s = nearest(trip_p.returns, _MAX_DATES_PER_LEG)
        c2s = nearest(trip_q.departs, _MAX_DATES_PER_LEG)
        q_rets = nearest(trip_q.returns, _MAX_DATES_PER_LEG)
        r_deps = nearest(trip_r.departs, _MAX_DATES_PER_LEG)
        stations = [
            x for x in dict.fromkeys(outer_stations) if x != HUB and x not in TW_AIRPORT_CODES
        ]
        first_legs = {x: {d: quote(self.provider, [(HUB, x, d)], adults) for d in p_deps} for x in stations}
        last_legs = {
            y: {d: quote(self.provider, [(y, HUB, d)], adults) for d in trip_r.returns} for y in stations
        }
        base_x = {x: self._cheapest_rt(x, trip_p, adults) for x in stations}
        base_y = {y: self._cheapest_rt(y, trip_r, adults) for y in stations}
        base_d: dict[str, TicketOffer | None] = {}
        plans: list[StrategyPlan] = []
        losers: list[tuple[int, StrategyPlan]] = []
        for x, y in product(stations, stations):
            if _country(y) == _country(x) or base_x[x] is None or base_y[y] is None:
                continue  # 頭尾不同國家: trip 3 must not revisit trip 1's country
            for dest in dict.fromkeys(destinations):
                if dest in (x, y, HUB) or dest in TW_AIRPORT_CODES:
                    continue
                if _country(dest) in (_country(x), _country(y)):
                    continue
                if dest not in base_d:
                    base_d[dest] = self._cheapest_rt(dest, trip_q, adults)
                if base_d[dest] is None:
                    continue
                baseline = base_x[x].total_price + base_d[dest].total_price + base_y[y].total_price
                best = self._best_loop(
                    x, y, dest, p_deps, c1s, c2s, q_rets, r_deps, first_legs[x], last_legs[y], adults
                )
                if best is None:
                    continue
                built = self._build(x, y, dest, trip_p, trip_q, trip_r, best, baseline)
                if best[0] < baseline:
                    plans.append(built)
                else:
                    losers.append((best[0] - baseline, built))
        plans.sort(key=lambda p: p.total_cost)
        if not plans and losers:  # show the closest real comparison anyway
            plans.append(min(losers, key=lambda t: t[0])[1])
        return plans

    # ------------------------------------------------------------------
    def _cheapest_rt(self, dest: str, slot: TripSlot, adults: int) -> TicketOffer | None:
        return cheapest([
            t
            for dep, ret in product(slot.departs, slot.returns)
            if ret > dep
            for t in self.provider.search(
                origin=HUB, destination=dest, departure_date=dep, return_date=ret, adults=adults
            )
        ])

    def _best_loop(self, x, y, dest, p_deps, c1s, c2s, q_rets, r_deps, first_legs, last_legs, adults):
        best = None
        for c1, c2, q_ret, r_dep in product(c1s, c2s, q_rets, r_deps):
            if not (c1 < c2 < q_ret < r_dep):
                continue
            firsts = [(t.total_price, d, t) for d, t in first_legs.items() if t and d < c1]
            lasts = [(t.total_price, d, t) for d, t in last_legs.items() if t and d > r_dep]
            if not firsts or not lasts:
                continue
            _, p_dep, first = min(firsts, key=lambda o: o[0])
            _, r_ret, last = min(lasts, key=lambda o: o[0])
            if best and first.total_price + last.total_price >= best[0]:
                continue
            four = quote(
                self.provider,
                [(x, HUB, c1), (HUB, dest, c2), (dest, HUB, q_ret), (HUB, y, r_dep)],
                adults,
            )
            if four is None or len(four.legs) < 4:
                continue
            total = first.total_price + four.total_price + last.total_price
            if best is None or total < best[0]:
                best = (total, (p_dep, c1, c2, q_ret, r_dep, r_ret), (first, four, last), [])
        return best

    def _build(self, x, y, dest, p: TripSlot, q: TripSlot, r: TripSlot, best, baseline) -> StrategyPlan:
        total, (p_dep, c1, c2, q_ret, r_dep, r_ret), (first, four, last), conn_warnings = best
        x_name = BY_CODE[x].name_zh if x in BY_CODE else x
        trips = (
            (
                f"旅程 1｜{p.label}：{fmt_day(p_dep)} {HUB}→{x}（單買初段）· 外站停留不限"
                f" ⇢ {fmt_day(c1)} {x}→{HUB}（四腿票 第1段）"
            ),
            (
                f"旅程 2｜{q.label}：{fmt_day(c2)} {HUB}→{dest}（第2段）"
                f" ⇢ {fmt_day(q_ret)} {dest}→{HUB}（第3段）"
            ),
            (
                f"旅程 3｜{r.label}：{fmt_day(r_dep)} {HUB}→{y}（第4段）"
                f" ⇢ {fmt_day(r_ret)} {y}→{HUB}（單買最後一段 或 下一張四腿票第1段＝循環）"
            ),
        )
        saving = baseline - total
        warnings = [
            *conn_warnings,
            RiskWarning(
                RiskLevel.MEDIUM,
                "four_leg_first_segment",
                f"四腿票第1段 {x}→{HUB} 必須搭乘（它是旅程 1 的回程，日期在 {p.label} 時段內），"
                "未搭乘後續航段全部作廢，所以旅程 1 的去程要先單買",
            ),
            RiskWarning(
                RiskLevel.LOW,
                "four_leg_loop",
                f"最後一段 {y}→{HUB} 也可改搭下一張{y}出發四腿票的第1段（循環），省下這張單程",
            ),
            saving_warning(
                "four_leg_savings_estimate",
                f"三趟各買 {HUB}⇄{x}、{HUB}⇄{dest}、{HUB}⇄{y} 一般來回",
                baseline,
                total,
            ),
            RiskWarning(
                RiskLevel.MEDIUM,
                "four_leg_origin_open_jaw",
                f"第1段從 {x} 出發、第4段飛 {y}（不同國家）＝起點開口：是否能整張開票依航空公司"
                "票價規則而定，以 Google Flights / Trip.com 多段整張報價為準",
            ),
        ]
        return StrategyPlan(
            strategy=self.strategy,
            tickets=(first, four, last),
            total_cost=total,
            currency=four.currency,
            total_travel_days=(c1 - p_dep).days + 1 + (q_ret - c2).days + 1 + (r_ret - r_dep).days + 1,
            warnings=tuple(warnings),
            explain=f"四腿票 {x}→{HUB}→{dest}→{HUB}→{y}（{x_name} 出發，3 趟旅程）＋單買初段/最後一段，"
            + (f"三趟省 {saving:,}" if saving > 0 else f"比三張一般來回多 {-saving:,}（實價不划算）"),
            ticket_roles=("單買初段", f"外站四腿票：{x} 出發", "單買最後一段"),
            trips=trips,
        )
