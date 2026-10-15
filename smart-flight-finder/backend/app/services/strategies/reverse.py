"""Reverse ticketing analyzer.

比較兩個方向的來回票價差 — 若「反向開票」+ 棄用部分段 (或實際使用外站當真起點)
後總價顯著低於正向，產出一個策略建議。

此實作僅做差價分析與風險標註；真實上線時需加上票規合法性檢查
(e.g. 棄程 / no-show 條款、里程計算等)。
"""

from __future__ import annotations

from datetime import date, timedelta

from app.models.enums import DateWindowRole, TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.services.date_matrix import ExpandedWindow
from app.services.strategies.base import (
    RiskLevel,
    RiskWarning,
    StrategyPlan,
)


class ReverseTicketPlanner:
    strategy = TicketStrategyType.REVERSE

    MIN_SAVINGS_PCT = 0.12  # 12% 以上才建議反向開票 (覆蓋風險)

    def __init__(self, provider: FlightOfferProvider) -> None:
        self.provider = provider

    def plan(
        self,
        *,
        expanded: list[ExpandedWindow],
        origins: list[str],
        destinations: list[str],
        adults: int = 1,
        max_results: int = 20,
    ) -> list[StrategyPlan]:
        plans: list[StrategyPlan] = []
        out_dates = sorted({
            c
            for w in expanded
            if w.role is DateWindowRole.OUTBOUND
            for c in w.candidates
        })
        ret_dates = sorted({
            c
            for w in expanded
            if w.role is DateWindowRole.RETURN
            for c in w.candidates
        })
        if not out_dates or not ret_dates:
            return plans

        for origin in origins:
            for destination in destinations:
                best = self._best_savings(
                    origin=origin,
                    destination=destination,
                    out_dates=out_dates,
                    ret_dates=ret_dates,
                    adults=adults,
                )
                if best is not None:
                    plans.append(best)
        plans.sort(key=lambda p: p.total_cost)
        return plans[:max_results]

    # ------------------------------------------------------------------
    def _best_savings(
        self,
        *,
        origin: str,
        destination: str,
        out_dates: list[date],
        ret_dates: list[date],
        adults: int,
    ) -> StrategyPlan | None:
        best_plan: StrategyPlan | None = None
        for out_date in out_dates:
            for ret_date in ret_dates:
                if (ret_date - out_date).days < 1:
                    continue
                forward = self._cheapest(
                    origin, destination, out_date, ret_date, adults
                )
                reverse = self._cheapest(
                    destination, origin,
                    out_date - timedelta(days=0),
                    ret_date,
                    adults,
                )
                if forward is None or reverse is None:
                    continue
                savings = forward.total_price - reverse.total_price
                if savings <= 0:
                    continue
                savings_pct = savings / max(forward.total_price, 1)
                if savings_pct < self.MIN_SAVINGS_PCT:
                    continue

                warnings = (
                    RiskWarning(
                        level=RiskLevel.MEDIUM,
                        code="reverse_fare_rules",
                        message="反向開票需確認票規允許棄程/缺省段；里程通常不計入。",
                    ),
                    RiskWarning(
                        level=RiskLevel.LOW,
                        code="reverse_savings_estimate",
                        message=f"估計節省 {savings:,} {reverse.currency}（{savings_pct:.0%}）",
                    ),
                )
                plan = StrategyPlan(
                    strategy=self.strategy,
                    tickets=(reverse,),
                    total_cost=reverse.total_price,
                    currency=reverse.currency,
                    total_travel_days=(ret_date - out_date).days + 1,
                    warnings=warnings,
                    explain=(
                        f"反向：{destination}→{origin}→{destination} 的來回票"
                        f" {out_date}~{ret_date}，較正向 {origin}→{destination}"
                        f" 來回便宜 {savings:,}"
                    ),
                )
                if best_plan is None or plan.total_cost < best_plan.total_cost:
                    best_plan = plan
        return best_plan

    def _cheapest(self, origin, destination, out_date, ret_date, adults):
        offers = self.provider.search(
            origin=origin,
            destination=destination,
            departure_date=out_date,
            return_date=ret_date,
            adults=adults,
        )
        return min(offers, key=lambda o: o.total_price) if offers else None
