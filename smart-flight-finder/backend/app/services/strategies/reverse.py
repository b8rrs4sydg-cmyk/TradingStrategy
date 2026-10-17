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

A plan is always exactly TWO tickets (the 包覆票 and the 反向票; the 補頭尾
variant with three tickets was dropped) and is kept only if it beats buying
two ordinary round trips (otherwise the closest comparison is shown).

Entry and exit of one trip may differ inside the same country (大阪進、東京
出), so each trip has its own in/out city: A = H→A_in … A_out→H, B = H→B_in
… B_out→H. The 包覆票 is H→A_in + B_out→H and the 反向票 A_out→H + H→B_in;
when a ticket's two ends differ it is an open jaw priced as multi-city.
倒買法 is only practical on Asian short-haul where foreign-origin round
trips are sold cheaply (Japan, Thailand, sometimes Korea) — other countries
are skipped (see ``DAOMAI_COUNTRIES``).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.data.airports import BY_CODE
from app.models.enums import TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.services.strategies.base import RiskLevel, RiskWarning, StrategyPlan, TicketOffer
from app.services.strategies.two_trip import (
    TripSlot,
    best_pair,
    cheapest,
    fmt_day,
    quote,
    saving_warning,
)

_Front = tuple[date, date, tuple[TicketOffer, ...]]  # (a_dep, b_ret, tickets)
_Back = tuple[date, date, TicketOffer]               # (a_ret, b_dep, 反向票)

DAOMAI_COUNTRIES = frozenset({"JP", "TH", "KR"})
_MAX_PLANS_PER_COUNTRY = 6


def daomai_country(code: str) -> str | None:
    a = BY_CODE.get(code)
    return a.country if a and a.country in DAOMAI_COUNTRIES else None


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
            by_country: dict[str, list[str]] = {}
            for d in dict.fromkeys(destinations):
                c = daomai_country(d)
                if c and d != home:
                    by_country.setdefault(c, []).append(d)
            for dests in by_country.values():
                plans += self._plan_country(home, dests, trip_a, trip_b, adults)
        plans.sort(key=lambda p: p.total_cost)
        return plans

    def _plan_country(self, home, dests, a: TripSlot, b: TripSlot, adults) -> list[StrategyPlan]:
        rt_a = [t for d in dests if (t := self._baseline(home, d, a, adults))]
        rt_b = [t for d in dests if (t := self._baseline(home, d, b, adults))]
        if not rt_a or not rt_b:
            return []
        # Ordinary alternative: the cheapest plain round trip into this country, per trip.
        baseline = cheapest(rt_a).total_price + cheapest(rt_b).total_price
        backs = {
            (a_out, b_in): self._reverse_tickets(home, a_out, b_in, a, b, adults)
            for a_out in dests
            for b_in in dests
        }
        fronts = {
            (variant, a_in, b_out): front
            for a_in in dests
            for b_out in dests
            for variant, front in (("倒買法", self._wrap_tickets(home, a_in, b_out, a, b, adults)),)
        }
        out, losers = [], []
        for (variant, a_in, b_out), front in fronts.items():
            for (a_out, b_in), back in backs.items():
                best = best_pair(front, back, _compatible)
                if best is None:
                    continue
                built = self._build(variant, home, (a_in, a_out), (b_in, b_out), a, b, best, baseline)
                (out if best[0] < baseline else losers).append(built)
        out.sort(key=lambda p: p.total_cost)
        if not out and losers:  # show the closest real comparison anyway
            out.append(min(losers, key=lambda p: p.total_cost))
        return out[:_MAX_PLANS_PER_COUNTRY]

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

    def _reverse_tickets(self, home, a_out, b_in, a: TripSlot, b: TripSlot, adults) -> list[tuple[int, _Back]]:
        out = []
        for a_ret in a.returns:
            for b_dep in b.departs:
                if b_dep <= a_ret:
                    continue
                t = quote(self.provider, [(a_out, home, a_ret), (home, b_in, b_dep)], adults)
                if t:
                    out.append((t.total_price, (a_ret, b_dep, t)))
        return out

    def _wrap_tickets(self, home, a_in, b_out, a: TripSlot, b: TripSlot, adults) -> list[tuple[int, _Front]]:
        out = []
        for a_dep in a.departs:
            for b_ret in b.returns:
                t = quote(self.provider, [(home, a_in, a_dep), (b_out, home, b_ret)], adults)
                if t:
                    out.append((t.total_price, (a_dep, b_ret, (t,))))
        return out

    def _build(self, variant, home, trip_a_cities, trip_b_cities, a: TripSlot, b: TripSlot, best, baseline) -> StrategyPlan:
        total, (a_dep, b_ret, front), (a_ret, b_dep, rev) = best
        (a_in, a_out), (b_in, b_out) = trip_a_cities, trip_b_cities
        rev_role = f"反向票：{a_out} 出發" + (f"，回程飛 {b_in}" if b_in != a_out else "")
        (wrap,) = front   # always two tickets: 包覆票 + 反向票
        tickets = (wrap, rev)
        roles = (f"包覆票：{home} 出發" + (f"，{b_out} 回" if b_out != a_in else ""), rev_role)
        first_tag, last_tag = "包覆票 第1段", "包覆票 第2段"

        trips = (
            (
                f"旅程 A｜{a.label}：{fmt_day(a_dep)} {home}→{a_in}（{first_tag}）"
                f" ⇢ {fmt_day(a_ret)} {a_out}→{home}（反向票 第1段）"
            ),
            (
                f"旅程 B｜{b.label}：{fmt_day(b_dep)} {home}→{b_in}（反向票 第2段）"
                f" ⇢ {fmt_day(b_ret)} {b_out}→{home}（{last_tag}）"
            ),
        )
        saving = baseline - total
        warnings = [
            RiskWarning(
                RiskLevel.MEDIUM,
                "reverse_ticket_order",
                f"反向票須從第1段 {a_out}→{home} 開始依序搭乘，第1段未搭乘後段會被取消；"
                "各張票分開開票，任一張延誤或改期都不保護另一張",
            ),
            saving_warning("reverse_savings_estimate", "兩趟各買一般來回", baseline, total),
        ]
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
            explain=f"反向票＋{variant}：旅程A {_route(a_in, a_out)}、旅程B {_route(b_in, b_out)}"
            f"，共 {len(tickets)} 張票，"
            + (f"省 {saving:,}" if saving > 0 else f"比一般來回多 {-saving:,}（實價不划算）"),
            ticket_roles=roles,
            trips=trips,
        )


def _compatible(front: _Front, back: _Back) -> bool:
    a_dep, b_ret, _ = front
    a_ret, b_dep, _ = back
    return a_dep < a_ret and b_dep < b_ret


def _route(city_in: str, city_out: str) -> str:
    return city_in if city_in == city_out else f"{city_in}進{city_out}出"
