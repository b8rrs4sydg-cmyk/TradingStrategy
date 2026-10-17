"""反向票 + 倒買法 — two trips (A then B) from two interleaved tickets.

For a traveller living in Taiwan (home H) visiting D1 on trip A and D2 on
trip B:

    反向票 (foreign-origin round trip, the cheap one in TW holidays)
        D1 → H   at the end of trip A
        H  → D2  at the start of trip B
    倒買法: 包覆票 (home-origin round trip wrapping both trips)
        H  → D1  at the start of trip A
        D2 → H   at the end of trip B

    旅程 A = 包覆票去程 + 反向票去程;  旅程 B = 反向票回程 + 包覆票回程

The other common way to use the 反向票 is to 補頭尾 — buy the first
H→D1 and last D2→H as two one-ways instead of the 包覆票. Both variants
are priced; each is kept only if it beats buying two ordinary round trips.
D1 == D2 is the classic case; D1 != D2 is the 名古屋/東京-style variant
(each ticket then becomes an open-jaw, priced as multi-city).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.models.enums import TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.services.strategies.base import RiskLevel, RiskWarning, StrategyPlan, TicketOffer
from app.services.strategies.two_trip import TripSlot, best_pair, cheapest, fmt_day, quote

_Front = tuple[date, date, tuple[TicketOffer, ...]]  # (a_dep, b_ret, tickets)
_Back = tuple[date, date, TicketOffer]               # (a_ret, b_dep, 反向票)


class ReverseTicketPlanner:
    strategy = TicketStrategyType.REVERSE

    def __init__(self, provider: FlightOfferProvider) -> None:
        self.provider = provider

    def plan(
        self,
        *,
        trip_a: TripSlot,
        trip_b: TripSlot,
        origins: Sequence[str],
        destinations: Sequence[str],
        adults: int = 1,
    ) -> list[StrategyPlan]:
        plans: list[StrategyPlan] = []
        for home in origins:
            dests = [d for d in dict.fromkeys(destinations) if d != home]
            base_a = {d: self._baseline(home, d, trip_a, adults) for d in dests}
            base_b = {d: self._baseline(home, d, trip_b, adults) for d in dests}
            for d1 in dests:
                for d2 in dests:
                    if base_a[d1] is None or base_b[d2] is None:
                        continue
                    baseline = base_a[d1].total_price + base_b[d2].total_price
                    back = self._reverse_tickets(home, d1, d2, trip_a, trip_b, adults)
                    for variant, front in (
                        ("倒買法", self._wrap_tickets(home, d1, d2, trip_a, trip_b, adults)),
                        ("補頭尾", self._one_way_pairs(home, d1, d2, trip_a, trip_b, adults)),
                    ):
                        best = best_pair(front, back, _compatible)
                        if best is None or best[0] >= baseline:
                            continue
                        plans.append(
                            self._build(variant, home, d1, d2, trip_a, trip_b, best, baseline)
                        )
        plans.sort(key=lambda p: p.total_cost)
        return plans

    # ------------------------------------------------------------------
    def _baseline(self, home: str, d: str, slot: TripSlot, adults: int) -> TicketOffer | None:
        offers = [
            t
            for dep in slot.departs
            for ret in slot.returns
            if ret > dep
            for t in self.provider.search(
                origin=home, destination=d, departure_date=dep, return_date=ret, adults=adults
            )
        ]
        return cheapest(offers)

    def _reverse_tickets(self, home, d1, d2, a: TripSlot, b: TripSlot, adults) -> list[tuple[int, _Back]]:
        out = []
        for a_ret in a.returns:
            for b_dep in b.departs:
                if b_dep <= a_ret:
                    continue
                t = quote(self.provider, [(d1, home, a_ret), (home, d2, b_dep)], adults)
                if t:
                    out.append((t.total_price, (a_ret, b_dep, t)))
        return out

    def _wrap_tickets(self, home, d1, d2, a: TripSlot, b: TripSlot, adults) -> list[tuple[int, _Front]]:
        out = []
        for a_dep in a.departs:
            for b_ret in b.returns:
                t = quote(self.provider, [(home, d1, a_dep), (d2, home, b_ret)], adults)
                if t:
                    out.append((t.total_price, (a_dep, b_ret, (t,))))
        return out

    def _one_way_pairs(self, home, d1, d2, a: TripSlot, b: TripSlot, adults) -> list[tuple[int, _Front]]:
        firsts = [(dep, quote(self.provider, [(home, d1, dep)], adults)) for dep in a.departs]
        lasts = [(ret, quote(self.provider, [(d2, home, ret)], adults)) for ret in b.returns]
        return [
            (f.total_price + l_.total_price, (a_dep, b_ret, (f, l_)))
            for a_dep, f in firsts
            if f
            for b_ret, l_ in lasts
            if l_
        ]

    def _build(self, variant, home, d1, d2, a: TripSlot, b: TripSlot, best, baseline) -> StrategyPlan:
        total, (a_dep, b_ret, front), (a_ret, b_dep, rev) = best
        rev_role = f"反向票：{d1} 出發" + (f"，回程飛 {d2}" if d1 != d2 else "")
        if variant == "倒買法":
            (wrap,) = front
            tickets = (wrap, rev)
            roles = (f"包覆票：{home} 出發" + (f"，{d2} 回" if d1 != d2 else ""), rev_role)
            first_tag, last_tag = "包覆票 第1段", "包覆票 第2段"
        else:
            first, last = front
            tickets = (first, rev, last)
            roles = ("單買去程 (補頭)", rev_role, "單買回程 (補尾)")
            first_tag, last_tag = "單買去程", "單買回程"

        trips = (
            (
                f"旅程 A｜{a.label}：{fmt_day(a_dep)} {home}→{d1}（{first_tag}）"
                f" ⇢ {fmt_day(a_ret)} {d1}→{home}（反向票 第1段）"
            ),
            (
                f"旅程 B｜{b.label}：{fmt_day(b_dep)} {home}→{d2}（反向票 第2段）"
                f" ⇢ {fmt_day(b_ret)} {d2}→{home}（{last_tag}）"
            ),
        )
        saving = baseline - total
        warnings = [
            RiskWarning(
                RiskLevel.MEDIUM,
                "reverse_ticket_order",
                f"反向票須從第1段 {d1}→{home} 開始依序搭乘，第1段未搭乘後段會被取消；"
                "各張票分開開票，任一張延誤或改期都不保護另一張",
            ),
            RiskWarning(
                RiskLevel.LOW,
                "reverse_savings_estimate",
                f"比兩趟各買一般來回 (共 {baseline:,}) 省 {saving:,} TWD"
                f"（{saving / baseline:.0%}）",
            ),
        ]
        if variant == "倒買法":
            warnings.append(
                RiskWarning(
                    RiskLevel.LOW,
                    "wrap_ticket_validity",
                    f"包覆票從 {fmt_day(a_dep)} 用到 {fmt_day(b_ret)}，"
                    "請確認票價規則的最長停留 / 效期（常見為 1 年）",
                )
            )
        return StrategyPlan(
            strategy=self.strategy,
            tickets=tickets,
            total_cost=total,
            currency=rev.currency,
            total_travel_days=(a_ret - a_dep).days + 1 + (b_ret - b_dep).days + 1,
            warnings=tuple(warnings),
            explain=f"反向票＋{variant}：兩趟 {home}⇄{d1}" + (f" / {d2}" if d1 != d2 else "")
            + f"，共 {len(tickets)} 張票，省 {saving:,}",
            ticket_roles=roles,
            trips=trips,
        )


def _compatible(front: _Front, back: _Back) -> bool:
    a_dep, b_ret, _ = front
    a_ret, b_dep, _ = back
    return a_dep < a_ret and b_dep < b_ret
