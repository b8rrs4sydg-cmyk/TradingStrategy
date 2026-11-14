"""Open-jaw (開放式) planner.

Open-jaw = 不同進出點。使用者飛到 A，由 B 返航 (A ≠ B)；中間自行以陸路/
國內線移動 (例如：東京進、大阪出，在日本國內搭新幹線)。

此策略以 **兩張單程票** 組合實現：

    票 1：TPE → A  (去程)
    票 2：B → TPE  (回程)

與 4-leg 不同處：兩張票的交接點 **不在同一機場**，所以沒有 MCT 問題，
但「兩票總價 vs 傳統 TPE↔A 來回」才有意義 — 本實作把它跟
cheapest-round-trip baseline 比，差額 > ``MIN_SAVINGS_PCT`` 才錄取。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.data.airports import BY_CODE
from app.data.metro import Tier, transfer
from app.models.enums import DateWindowRole, TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.services.date_matrix import ExpandedWindow
from app.services.strategies.base import (
    RiskLevel,
    RiskWarning,
    StrategyPlan,
    TicketOffer,
)


class OpenJawPlanner:
    strategy = TicketStrategyType.OPEN_JAW

    MIN_SAVINGS_PCT = 0.05  # 5% 以上才錄取 (open-jaw 風險比 4-leg 小很多)

    def __init__(self, provider: FlightOfferProvider, *, allow_separate: bool = False) -> None:
        self.provider = provider
        # tier 3 pairs (a flight between the two airports, e.g. 大阪進沖繩出) are off unless asked for
        self.allow_separate = allow_separate

    def plan(
        self,
        *,
        expanded: list[ExpandedWindow],
        origins: list[str],
        destinations: list[str],
        adults: int = 1,
        max_results: int = 20,
    ) -> list[StrategyPlan]:
        out_dates = sorted({c for w in expanded if w.role is DateWindowRole.OUTBOUND for c in w.candidates})
        ret_dates = sorted({c for w in expanded if w.role is DateWindowRole.RETURN for c in w.candidates})
        if not out_dates or not ret_dates or len(destinations) < 2:   # needs two airports of one country
            return []

        plans: list[StrategyPlan] = []
        # Baseline depends only on (origin, dest_a); dedupe across the (a, b)
        # pair enumeration where the same origin→a baseline would recompute.
        baseline_cache: dict[tuple[str, str], int] = {}

        def baseline_for(origin: str, dest_a: str) -> int:
            key = (origin, dest_a)
            if key not in baseline_cache:
                baseline_cache[key] = self._baseline_round_trip(
                    origin, dest_a, out_dates, ret_dates, adults
                )
            return baseline_cache[key]

        for origin in origins:
            for a, b in _distinct_pairs(destinations, allow_separate=self.allow_separate):
                # fair baseline: the cheaper of an ordinary round trip into either airport
                baseline = min((x for x in (baseline_for(origin, a), baseline_for(origin, b)) if x), default=0)
                for out_date in out_dates:
                    for ret_date in ret_dates:
                        if (ret_date - out_date).days < 1:
                            continue
                        plan = self._build(
                            origin=origin,
                            dest_a=a,
                            dest_b=b,
                            out_date=out_date,
                            ret_date=ret_date,
                            baseline=baseline,
                            adults=adults,
                        )
                        if plan is not None:
                            plans.append(plan)
        plans.sort(key=lambda p: p.total_cost)
        return plans[:max_results]

    # ------------------------------------------------------------------
    def _build(
        self,
        *,
        origin: str,
        dest_a: str,
        dest_b: str,
        out_date: date,
        ret_date: date,
        baseline: int,
        adults: int,
    ) -> StrategyPlan | None:
        outbound = self._cheapest(origin, dest_a, out_date, None, adults)
        inbound = self._cheapest(dest_b, origin, ret_date, None, adults)
        if outbound is None or inbound is None:
            return None
        hop = transfer(dest_a, dest_b)
        total = outbound.total_price + inbound.total_price + (hop.cost_twd or 0)
        if baseline and total >= baseline * (1 - self.MIN_SAVINGS_PCT):
            return None

        if hop.cost_twd is not None:
            hop_msg = f"已計入 {dest_a}→{dest_b} 地面交通約 {hop.cost_twd:,} TWD、{hop.minutes} 分鐘（估算）"
        else:
            hop_msg = f"{dest_a}→{dest_b} 之間需另搭航班或交通資料未驗證，費用未計入"
        warnings: list[RiskWarning] = [
            RiskWarning(
                level=RiskLevel.LOW if hop.tier <= Tier.GROUND else RiskLevel.MEDIUM,
                code="open_jaw_awareness",
                message=f"開放式行程（兩張獨立單程票）：{dest_a} 入境、{dest_b} 出境；{hop_msg}",
            )
        ]
        if baseline:
            savings = baseline - total
            if savings > 0:
                warnings.append(
                    RiskWarning(
                        level=RiskLevel.LOW,
                        code="open_jaw_savings_estimate",
                        message=f"較 {origin} 來回（{dest_a} 或 {dest_b}）估省 {savings:,} TWD",
                    )
                )

        return StrategyPlan(
            strategy=self.strategy,
            tickets=(outbound, inbound),
            total_cost=total,
            currency=outbound.currency,
            total_travel_days=(ret_date - out_date).days + 1,
            warnings=tuple(warnings),
            explain=f"Open-jaw：{origin}→{dest_a} ({out_date}) + {dest_b}→{origin} ({ret_date})",
            cost_complete=hop.cost_twd is not None,
            unknown_costs=() if hop.cost_twd is not None else (f"{dest_a}→{dest_b} 地面／國內交通",),
        )

    def _baseline_round_trip(
        self,
        origin: str,
        destination: str,
        out_dates: list[date],
        ret_dates: list[date],
        adults: int,
    ) -> int:
        best: int | None = None
        for out_date in out_dates:
            for ret_date in ret_dates:
                if (ret_date - out_date).days < 1:
                    continue
                rt = self._cheapest(origin, destination, out_date, ret_date, adults)
                if rt is None:
                    continue
                if best is None or rt.total_price < best:
                    best = rt.total_price
        return best or 0

    def _cheapest(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None,
        adults: int,
    ) -> TicketOffer | None:
        offers = self.provider.search(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        )
        return min(offers, key=lambda o: o.total_price) if offers else None


def _same_country(a: str, b: str) -> bool:
    ca, cb = BY_CODE.get(a), BY_CODE.get(b)
    return ca is not None and cb is not None and ca.country == cb.country


def _distinct_pairs(items: Iterable[str], *, allow_separate: bool = False) -> Iterable[tuple[str, str]]:
    """In/out airport pairs that are one reasonable trip: same country AND a known transfer (same metro area or a
    listed land link). Same country alone is not enough — 大阪進、沖繩出 needs a flight, so it is tier 3 and only
    allowed with ``allow_separate``; airports without metro data (tier 4) never pair."""

    seen = list(dict.fromkeys(items))  # preserve order, dedup
    for i, a in enumerate(seen):
        for b in seen[i + 1 :]:
            if not _same_country(a, b):
                continue
            tier = transfer(a, b).tier
            if tier <= Tier.GROUND or (allow_separate and tier == Tier.SEPARATE):
                yield a, b
                yield b, a
