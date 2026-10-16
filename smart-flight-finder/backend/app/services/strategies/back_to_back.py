"""Back-to-back 四段票 (XMN-TPE-NRT-TPE-XMN) pairing engine.

拼湊兩張互相獨立 PNR 的機票：

    票甲 (outer, 頭尾段)：外站 → TPE → 外站   (leg1, leg4)
    票乙 (inner, 中間段)：TPE → 目的地 → TPE  (leg2, leg3)

Timeline 必須合法：

    leg1 ──flight─→ TPE ─(MCT)─ TPE ─flight─→ 目的地 … (停留) …
                 目的地 ─flight─→ TPE ─(MCT)─ TPE ─flight─→ 外站 (leg4)

此實作的核心是：

1. 枚舉 (外站, 目的地, outer-dates, inner-dates) 的笛卡兒積，含剪枝；
2. 查詢票甲與票乙的最便宜 offer；
3. 兩次交接點做 MCT 驗證（跨票、國際線）；
4. 總價 = 甲 + 乙；若比 ``direct_round_trip_baseline`` 便宜一定門檻才錄取。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import product

from app.models.enums import DateWindowRole, TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.services.date_matrix import ExpandedWindow
from app.services.mct import DEFAULT_MCT, MctPolicy, check_cross_ticket_handoff
from app.services.strategies.base import (
    RiskLevel,
    RiskWarning,
    StrategyPlan,
    TicketOffer,
)


@dataclass(frozen=True, slots=True)
class _OuterDates:
    leg1_date: date   # 外站 → TPE
    leg4_date: date   # TPE → 外站


@dataclass(frozen=True, slots=True)
class _InnerDates:
    leg2_date: date   # TPE → 目的地
    leg3_date: date   # 目的地 → TPE


class FourLegPlanner:
    strategy = TicketStrategyType.BACK_TO_BACK_4LEG

    # 兩票總價至少要省到 baseline 直飛來回的 10% 才給建議
    MIN_SAVINGS_PCT = 0.10

    def __init__(
        self,
        provider: FlightOfferProvider,
        *,
        hub: str = "TPE",
        mct: MctPolicy = DEFAULT_MCT,
    ) -> None:
        self.provider = provider
        self.hub = hub
        self.mct = mct

    def plan(
        self,
        *,
        expanded: list[ExpandedWindow],
        outer_stations: Iterable[str],
        destinations: Iterable[str],
        outer_buffer_days: int = 2,
        adults: int = 1,
        max_results: int = 20,
    ) -> list[StrategyPlan]:
        inner_pairs = list(self._iter_inner_dates(expanded))
        if not inner_pairs:
            return []

        plans: list[StrategyPlan] = []

        # Baseline and inner_ticket both depend only on destination, not on
        # outer_station — precompute once per destination so adding a second
        # or third outer station is nearly free (fetches are deduped by the
        # provider cache anyway, but this also skips the Python call overhead).
        baseline_by_dest: dict[str, int] = {}
        inner_tickets_by_dest: dict[str, dict[_InnerDates, TicketOffer]] = {}
        for destination in destinations:
            baseline_by_dest[destination] = self._baseline_direct_round_trip(
                destination=destination,
                inner_pairs=inner_pairs,
                adults=adults,
            )
            per_dest: dict[_InnerDates, TicketOffer] = {}
            for inner in inner_pairs:
                tkt = self._cheapest_inner(
                    destination=destination, inner=inner, adults=adults
                )
                if tkt is not None:
                    per_dest[inner] = tkt
            inner_tickets_by_dest[destination] = per_dest

        for outer_station in outer_stations:
            for destination in destinations:
                baseline = baseline_by_dest[destination]
                inner_tickets = inner_tickets_by_dest[destination]
                for inner, inner_ticket in inner_tickets.items():
                    for outer in self._iter_outer_dates(inner, outer_buffer_days):
                        outer_ticket = self._cheapest_outer(
                            outer_station=outer_station,
                            outer=outer,
                            adults=adults,
                        )
                        if outer_ticket is None:
                            continue
                        plan = self._assemble(
                            outer_ticket=outer_ticket,
                            inner_ticket=inner_ticket,
                            outer=outer,
                            inner=inner,
                            baseline_price=baseline,
                            outer_station=outer_station,
                            destination=destination,
                        )
                        if plan is not None:
                            plans.append(plan)
        plans.sort(key=lambda p: p.total_cost)
        return plans[:max_results]

    # ------------------------------------------------------------------
    # Date enumeration
    # ------------------------------------------------------------------
    @staticmethod
    def _iter_inner_dates(expanded: list[ExpandedWindow]) -> Iterable[_InnerDates]:
        out = sorted({c for w in expanded if w.role is DateWindowRole.OUTBOUND for c in w.candidates})
        ret = sorted({c for w in expanded if w.role is DateWindowRole.RETURN for c in w.candidates})
        for leg2_date, leg3_date in product(out, ret):
            if leg3_date > leg2_date:
                yield _InnerDates(leg2_date=leg2_date, leg3_date=leg3_date)

    @staticmethod
    def _iter_outer_dates(inner: _InnerDates, buffer_days: int) -> Iterable[_OuterDates]:
        """票甲的頭段落地日 ∈ [leg2_date - buffer, leg2_date]
           票甲的尾段起飛日 ∈ [leg3_date, leg3_date + buffer]。
        """
        for leg1_offset in range(buffer_days + 1):
            leg1_date = inner.leg2_date - timedelta(days=leg1_offset)
            for leg4_offset in range(buffer_days + 1):
                leg4_date = inner.leg3_date + timedelta(days=leg4_offset)
                yield _OuterDates(leg1_date=leg1_date, leg4_date=leg4_date)

    # ------------------------------------------------------------------
    # Provider calls
    # ------------------------------------------------------------------
    def _cheapest_inner(self, *, destination, inner, adults) -> TicketOffer | None:
        offers = self.provider.search(
            origin=self.hub,
            destination=destination,
            departure_date=inner.leg2_date,
            return_date=inner.leg3_date,
            adults=adults,
        )
        return min(offers, key=lambda o: o.total_price) if offers else None

    def _cheapest_outer(self, *, outer_station, outer, adults) -> TicketOffer | None:
        offers = self.provider.search(
            origin=outer_station,
            destination=self.hub,
            departure_date=outer.leg1_date,
            return_date=outer.leg4_date,
            adults=adults,
        )
        return min(offers, key=lambda o: o.total_price) if offers else None

    def _baseline_direct_round_trip(
        self, *, destination, inner_pairs: list[_InnerDates], adults: int
    ) -> int:
        """Take the cheapest direct hub→destination round-trip over the inner matrix
        as the "do-nothing" baseline that we need to undercut.
        """
        best = None
        for pair in inner_pairs:
            offers = self.provider.search(
                origin=self.hub,
                destination=destination,
                departure_date=pair.leg2_date,
                return_date=pair.leg3_date,
                adults=adults,
            )
            if not offers:
                continue
            cheapest = min(o.total_price for o in offers)
            if best is None or cheapest < best:
                best = cheapest
        return best or 0

    # ------------------------------------------------------------------
    # Assembly + validation
    # ------------------------------------------------------------------
    def _assemble(
        self,
        *,
        outer_ticket: TicketOffer,
        inner_ticket: TicketOffer,
        outer: _OuterDates,
        inner: _InnerDates,
        baseline_price: int,
        outer_station: str,
        destination: str,
    ) -> StrategyPlan | None:
        total = outer_ticket.total_price + inner_ticket.total_price
        if baseline_price and total >= baseline_price * (1 - self.MIN_SAVINGS_PCT):
            return None

        warnings: list[RiskWarning] = list(
            check_cross_ticket_handoff(
                _half_ticket(outer_ticket, 0),      # XMN→TPE arrival half
                _half_ticket(inner_ticket, 0),      # TPE→NRT departure half
                policy=self.mct,
            )
        )
        warnings.extend(
            check_cross_ticket_handoff(
                _half_ticket(inner_ticket, 1),      # NRT→TPE arrival half
                _half_ticket(outer_ticket, 1),      # TPE→XMN departure half
                policy=self.mct,
            )
        )
        if any(w.level is RiskLevel.HIGH for w in warnings):
            # Timeline invalid — skip rather than recommend.
            return None

        warnings.append(
            RiskWarning(
                level=RiskLevel.MEDIUM,
                code="back_to_back_awareness",
                message=(
                    "四段票為兩張獨立 PNR，任何改期/取消/延誤皆不互相保護；"
                    "行李須入境提領後重新託運。"
                ),
            )
        )
        savings = baseline_price - total if baseline_price else 0
        if savings > 0:
            warnings.append(
                RiskWarning(
                    level=RiskLevel.LOW,
                    code="back_to_back_savings_estimate",
                    message=f"較直飛來回估省 {savings:,} TWD",
                )
            )

        total_travel_days = (inner.leg3_date - inner.leg2_date).days + 1
        return StrategyPlan(
            strategy=self.strategy,
            tickets=(outer_ticket, inner_ticket),
            total_cost=total,
            currency=outer_ticket.currency,
            total_travel_days=total_travel_days,
            warnings=tuple(warnings),
            explain=(
                f"四段票：{outer_station}-{self.hub}-{destination}-{self.hub}-{outer_station}; "
                f"票甲 {outer.leg1_date}/{outer.leg4_date}, 票乙 {inner.leg2_date}/{inner.leg3_date}"
            ),
        )


def _half_ticket(ticket: TicketOffer, leg_index: int) -> TicketOffer:
    """Return a lightweight view containing just one leg (for MCT checks)."""

    leg = ticket.legs[leg_index]
    return TicketOffer(
        offer_id=f"{ticket.offer_id}#{leg_index}",
        legs=(leg,),
        total_price=ticket.total_price,
        currency=ticket.currency,
        fare_class=ticket.fare_class,
        baggage_through_checked=ticket.baggage_through_checked,
        issuer=ticket.issuer,
    )
