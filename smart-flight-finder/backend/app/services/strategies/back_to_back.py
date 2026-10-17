"""外站四腿票 (四段票) — ONE ticket X→TPE→D→TPE→Y covering two trips.

The ticket is sold from an outstation X (a cheaper market than Taiwan):

    旅程 A:  leg1 X→TPE (c1)  +  leg2 TPE→D (c2 ≥ c1)   — c1 and c2 both inside
             trip A's chosen window, any stay in Taipei in between (no fixed
             outer-stay days, no separately bought 初段)
             … D … leg3 D→TPE                            (a_ret)
    旅程 B:  leg4 TPE→Y (b_dep)  … Y …  單買最後一段 Y→TPE (b_ret)

Leg 1 must be flown (skipping it cancels the rest). The 最後一段 can instead be
leg 1 of the next 四腿票 — chaining tickets this way is the 循環.

頭尾不同國家: trip A already starts in X and then visits D, so leg 4 must land
in a THIRD country (Y not in X's or D's country) — otherwise both trips go to
the same country. Either end can move: the planner tries every (X, Y) pair of
the chosen outstations. Such an origin open jaw is priced by Google Flights as
one multi-city ticket; airline rules on it vary, hence a warning. Each plan
prices the closed loop against an ordinary round trip to D on trip A plus one
to Y on trip B; if no combination saves money, the cheapest one is still
returned, flagged ``no_saving``, so the real comparison stays visible.
"""

from __future__ import annotations

from collections.abc import Sequence
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
        adults: int = 1,
    ) -> list[StrategyPlan]:
        a_deps = nearest(trip_a.departs, _MAX_DATES_PER_LEG)
        a_rets = nearest(trip_a.returns, _MAX_DATES_PER_LEG)
        b_deps = nearest(trip_b.departs, _MAX_DATES_PER_LEG)
        plans: list[StrategyPlan] = []
        stations = [
            x for x in dict.fromkeys(outer_stations) if x != HUB and x not in TW_AIRPORT_CODES
        ]
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
                best = self._best_loop(x, y, dest, a_deps, a_rets, b_deps, last_legs[y], adults)
                if best is None:
                    continue
                built = self._build(x, y, dest, trip_a, trip_b, best, baseline)
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

    def _best_loop(self, x, y, dest, a_deps, a_rets, b_deps, last_legs, adults):
        best = None
        for c1, c2, a_ret, b_dep in product(a_deps, a_deps, a_rets, b_deps):
            if not (c1 <= c2 < a_ret < b_dep):
                continue
            last_options = [(t.total_price, d, t) for d, t in last_legs.items() if t and d > b_dep]
            if not last_options:
                continue
            _, b_ret, last = min(last_options, key=lambda o: o[0])
            four = quote(
                self.provider,
                [(x, HUB, c1), (HUB, dest, c2), (dest, HUB, a_ret), (HUB, y, b_dep)],
                adults,
            )
            if four is None or len(four.legs) < 4:
                continue
            total = four.total_price + last.total_price
            if best and total >= best[0]:
                continue
            warnings = self._connection_warnings(four, c1, c2)
            if any(w.level is RiskLevel.HIGH for w in warnings):
                continue
            best = (total, (c1, c2, a_ret, b_dep, b_ret), (four, last), warnings)
        return best

    def _connection_warnings(self, four: TicketOffer, c1, c2) -> list[RiskWarning]:
        out: list[RiskWarning] = []
        if c1 == c2:
            w = check_connection(four.legs[0], four.legs[1], cross_ticket=False, policy=self.mct)
            if w:
                out.append(w)
        else:
            out.append(
                RiskWarning(
                    RiskLevel.MEDIUM,
                    "four_leg_second_stopover",
                    f"第1→2段在台北隔 {(c2 - c1).days} 天：算第二次中停，請確認票價規則是否允許（常見限制或加價）",
                )
            )
        return out

    def _build(self, x, y, dest, a: TripSlot, b: TripSlot, best, baseline) -> StrategyPlan:
        total, (c1, c2, a_ret, b_dep, b_ret), (four, last), conn_warnings = best
        x_name = BY_CODE[x].name_zh if x in BY_CODE else x
        leg12 = (
            f"{fmt_day(c1)} {x}→{HUB}→{dest}（四腿票 第1+2段，台北轉機）"
            if c1 == c2
            else f"{fmt_day(c1)} {x}→{HUB}（四腿票 第1段）⇢ 台北停留 {(c2 - c1).days} 天 ⇢ "
            f"{fmt_day(c2)} {HUB}→{dest}（第2段）"
        )
        trips = (
            f"旅程 A｜{a.label}：{leg12} ⇢ {fmt_day(a_ret)} {dest}→{HUB}（第3段）",
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
                f"四腿票第1段 {x}→{HUB} 必須搭乘（日期在旅程 A 的時段內），未搭乘後續航段全部作廢",
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
            tickets=(four, last),
            total_cost=total,
            currency=four.currency,
            total_travel_days=(a_ret - c1).days + 1 + (b_ret - b_dep).days + 1,
            warnings=tuple(warnings),
            explain=f"四腿票 {x}→{HUB}→{dest}→{HUB}→{y}（{x_name} 出發，旅程B {_name(y)}）＋單買最後一段，"
            + (f"兩趟省 {saving:,}" if saving > 0 else f"比一般來回多 {-saving:,}（實價不划算）"),
            ticket_roles=(f"外站四腿票：{x} 出發", "單買最後一段"),
            trips=trips,
        )
