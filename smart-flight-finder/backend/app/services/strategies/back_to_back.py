"""外站四腿票 (四段票) — ONE ticket X→TPE→D→TPE→X covering two trips.

The ticket is sold from an outstation X (cheaper market than Taiwan, and leg
1 / leg 4 must be in the same country). For someone living in Taiwan:

    旅程 A:  單買初段 TPE→X (day a_dep)  … 外站停留 s 天 …
             leg1 X→TPE + leg2 TPE→D     (same day, <24h connection at TPE)
             … D … leg3 D→TPE            (a_ret; home stopover = the one >24h stop)
    旅程 B:  leg4 TPE→X                  (b_dep)  … X …
             單買最後一段 X→TPE           (b_ret)

Leg 1 must be flown (skipping it cancels the rest), which is why the loop
needs the separately bought 初段. The 最後一段 can instead be leg 1 of the
next 四腿票 — chaining tickets this way is the 循環. Each plan prices the
closed loop (both one-ways) and is kept only if it beats an ordinary round
trip to D on trip A plus one to X on trip B.
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
from app.services.strategies.two_trip import TripSlot, cheapest, fmt_day, nearest, quote

HUB = "TPE"
_MAX_DATES_PER_LEG = 5  # multi-city quotes are expensive on real APIs


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
        for x in dict.fromkeys(outer_stations):
            if x == HUB or x in TW_AIRPORT_CODES:
                continue
            first_legs = {d: quote(self.provider, [(HUB, x, d)], adults) for d in a_deps}
            last_legs = {d: quote(self.provider, [(x, HUB, d)], adults) for d in trip_b.returns}
            base_x = self._cheapest_rt(x, trip_b, adults)
            for dest in dict.fromkeys(destinations):
                if dest in (x, HUB) or dest in TW_AIRPORT_CODES:
                    continue
                base_d = self._cheapest_rt(dest, trip_a, adults)
                if base_x is None or base_d is None:
                    continue
                baseline = base_d.total_price + base_x.total_price
                best = self._best_loop(
                    x, dest, a_deps, a_rets, b_deps, trip_b.returns,
                    outer_stay_days, first_legs, last_legs, adults,
                )
                if best is None or best[0] >= baseline:
                    continue
                plans.append(self._build(x, dest, trip_a, trip_b, outer_stay_days, best, baseline))
        plans.sort(key=lambda p: p.total_cost)
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

    def _best_loop(self, x, dest, a_deps, a_rets, b_deps, b_rets, stay, first_legs, last_legs, adults):
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
                [(x, HUB, connect), (HUB, dest, connect), (dest, HUB, a_ret), (HUB, x, b_dep)],
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

    def _build(self, x, dest, a: TripSlot, b: TripSlot, stay, best, baseline) -> StrategyPlan:
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
                f"旅程 B｜{b.label}：{fmt_day(b_dep)} {HUB}→{x}（四腿票 第4段）"
                f" ⇢ {fmt_day(b_ret)} {x}→{HUB}（單買最後一段 或 下一張四腿票第1段＝循環）"
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
                f"最後一段 {x}→{HUB} 也可改搭下一張四腿票的第1段（循環），省下這張單程",
            ),
            RiskWarning(
                RiskLevel.LOW,
                "four_leg_savings_estimate",
                f"比旅程A買 {HUB}⇄{dest}、旅程B買 {HUB}⇄{x} 一般來回 (共 {baseline:,})"
                f" 省 {saving:,} TWD（{saving / baseline:.0%}）",
            ),
        ]
        return StrategyPlan(
            strategy=self.strategy,
            tickets=(first, four, last),
            total_cost=total,
            currency=four.currency,
            total_travel_days=(a_ret - a_dep).days + 1 + (b_ret - b_dep).days + 1,
            warnings=tuple(warnings),
            explain=f"四腿票 {x}→{HUB}→{dest}→{HUB}→{x}（{x_name} 外站）＋單買初段/最後一段，"
            f"兩趟省 {saving:,}",
            ticket_roles=("單買初段", f"外站四腿票：{x} 出發", "單買最後一段"),
            trips=trips,
        )
