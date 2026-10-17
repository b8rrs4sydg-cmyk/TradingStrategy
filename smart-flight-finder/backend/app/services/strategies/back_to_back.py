"""外站四腿票 (四段票) — ONE ticket X→TPE→D→TPE→Y covering two trips.

The ticket is sold from an outstation X (a cheaper market than Taiwan). For
someone living in Taiwan:

    旅程 A:  單買初段 TPE→X (day a_dep)  … 外站停留 s 天 …
             leg1 X→TPE + leg2 TPE→D     (same day, <24h connection at TPE)
             … D … leg3 D→TPE            (a_ret; home stopover = the one >24h stop)
    旅程 B:  leg4 TPE→Y                  (b_dep)  … Y …
             單買最後一段 Y→TPE           (b_ret)

Leg 1 must be flown (skipping it cancels the rest), which is why the loop
needs the separately bought 初段. The 最後一段 can instead be leg 1 of the
next 四腿票 — chaining tickets this way is the 循環.

頭尾不同國家: trip A already spends the outer stay in X and then visits D,
so leg 4 must land in a THIRD country (Y not in X's or D's country) —
otherwise both trips go to the same country. Either end can move: the
planner tries every (X, Y) pair of the chosen outstations. Such an origin
open jaw is priced by Google Flights as one multi-city ticket; airline rules
on it vary, hence a warning. Each plan prices the closed loop (both
one-ways) against an ordinary round trip to D on trip A plus one to Y on
trip B; if no combination saves money, the cheapest one is still returned,
flagged ``no_saving``, so the real comparison stays visible.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from itertools import product

from app.data.airports import BY_CODE, TW_AIRPORT_CODES
from app.models.enums import TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.services.mct import DEFAULT_MCT, MctPolicy, check_connection
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
        trip_a: TripSlot,
        trip_b: TripSlot,
        outer_stations: Sequence[str],
        destinations: Sequence[str],
        outer_stay_days: int = 2,
        adults: int = 1,
    ) -> list[StrategyPlan]:
        a_deps = nearest(trip_a.departs, _MAX_DATES_PER_LEG)
        a_rets = nearest(trip_a.returns, _MAX_DATES_PER_LEG)
        b_deps = nearest(trip_b.departs, _MAX_DATES_PER_LEG)
        plans: list[StrategyPlan] = []
        stations = [
            x for x in dict.fromkeys(outer_stations) if x != HUB and x not in TW_AIRPORT_CODES
        ]
        first_legs = {x: {d: quote(self.provider, [(HUB, x, d)], adults) for d in a_deps} for x in stations}
        last_legs = {
            y: {d: quote(self.provider, [(y, HUB, d)], adults) for d in trip_b.returns} for y in stations
        }
        base_y = {y: self._cheapest_rt(y, trip_b, adults) for y in stations}
        base_d = {}
        losers: list[tuple[int, StrategyPlan]] = []
        for x, y in product(stations, stations):
            if _country(y) == _country(x):
                continue  # 頭尾不同國家: trip B must not revisit the outstation country
            for dest in dict.fromkeys(destinations):
                if dest in (x, y, HUB) or dest in TW_AIRPORT_CODES or _country(dest) == _country(y):
                    continue
                if dest not in base_d:
                    base_d[dest] = self._cheapest_rt(dest, trip_a, adults)
                if base_y[y] is None or base_d[dest] is None:
                    continue
                baseline = base_d[dest].total_price + base_y[y].total_price
                best = self._best_loop(
                    x, y, dest, a_deps, a_rets, b_deps, outer_stay_days,
                    first_legs[x], last_legs[y], adults,
                )
                if best is None:
                    continue
                built = self._build(x, y, dest, trip_a, trip_b, outer_stay_days, best, baseline)
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

    def _best_loop(self, x, y, dest, a_deps, a_rets, b_deps, stay, first_legs, last_legs, adults):
        best = None
        for a_dep, a_ret, b_dep in product(a_deps, a_rets, b_deps):
            connect = a_dep + timedelta(days=stay)
            if not (connect < a_ret < b_dep):
                continue
            first = first_legs.get(a_dep)
            last_options = [
                (t.total_price, d, t) for d, t in last_legs.items() if t and d > b_dep
            ]
            if first is None or not last_options:
                continue
            _, b_ret, last = min(last_options, key=lambda o: o[0])
            if best and first.total_price + last.total_price >= best[0]:
                continue
            four = quote(
                self.provider,
                [(x, HUB, connect), (HUB, dest, connect), (dest, HUB, a_ret), (HUB, y, b_dep)],
                adults,
            )
            if four is None or len(four.legs) < 4:
                continue
            warnings = self._connection_warnings(first, four, stay)
            if any(w.level is RiskLevel.HIGH for w in warnings):
                continue
            total = first.total_price + four.total_price + last.total_price
            if best is None or total < best[0]:
                best = (total, (a_dep, a_ret, b_dep, b_ret), (first, four, last), warnings)
        return best

    def _connection_warnings(self, first: TicketOffer, four: TicketOffer, stay: int) -> list[RiskWarning]:
        out: list[RiskWarning] = []
        leg1, leg2 = four.legs[0], four.legs[1]
        if stay == 0:
            w = check_connection(first.last_leg(), leg1, cross_ticket=True, policy=self.mct)
            if w:
                out.append(w)
        w = check_connection(leg1, leg2, cross_ticket=False, policy=self.mct)
        if w:
            out.append(w)
        if leg2.departure - leg1.arrival >= timedelta(hours=24):
            out.append(
                RiskWarning(
                    RiskLevel.HIGH,
                    "four_leg_second_stopover",
                    "第1→2段在台北超過 24 小時會變成第二次中停，票價規則通常不允許或要加價",
                )
            )
        return out

    def _build(self, x, y, dest, a: TripSlot, b: TripSlot, stay, best, baseline) -> StrategyPlan:
        total, (a_dep, a_ret, b_dep, b_ret), (first, four, last), conn_warnings = best
        connect = a_dep + timedelta(days=stay)
        x_name = BY_CODE[x].name_zh if x in BY_CODE else x
        stay_txt = f"外站停留 {stay} 天" if stay else "同日接續"
        trips = (
            (
                f"旅程 A｜{a.label}：{fmt_day(a_dep)} {HUB}→{x}（單買初段）· {stay_txt}"
                f" ⇢ {fmt_day(connect)} {x}→{HUB}→{dest}（四腿票 第1+2段，台北轉機 <24h）"
                f" ⇢ {fmt_day(a_ret)} {dest}→{HUB}（第3段，回台中停）"
            ),
            (
                f"旅程 B｜{b.label}：{fmt_day(b_dep)} {HUB}→{y}（四腿票 第4段）"
                f" ⇢ {fmt_day(b_ret)} {y}→{HUB}（單買最後一段 或 下一張四腿票第1段＝循環）"
            ),
        )
        saving = baseline - total
        warnings = [
            *conn_warnings,
            RiskWarning(
                RiskLevel.MEDIUM,
                "four_leg_first_segment",
                f"四腿票第1段 {x}→{HUB} 必須搭乘，未搭乘後續航段全部作廢 —"
                "所以要先單買初段飛到外站",
            ),
            RiskWarning(
                RiskLevel.LOW,
                "four_leg_loop",
                f"最後一段 {y}→{HUB} 也可改搭下一張{y}出發四腿票的第1段（循環），省下這張單程",
            ),
            saving_warning(
                "four_leg_savings_estimate",
                f"旅程A買 {HUB}⇄{dest}、旅程B買 {HUB}⇄{y} 一般來回",
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
            total_travel_days=(a_ret - a_dep).days + 1 + (b_ret - b_dep).days + 1,
            warnings=tuple(warnings),
            explain=f"四腿票 {x}→{HUB}→{dest}→{HUB}→{y}（{x_name} 外站"
            + f"，旅程B {_name(y)}）＋單買初段/最後一段，"
            + (f"兩趟省 {saving:,}" if saving > 0 else f"比一般來回多 {-saving:,}（實價不划算）"),
            ticket_roles=("單買初段", f"外站四腿票：{x} 出發", "單買最後一段"),
            trips=trips,
        )
