"""多維度評分：價格 / 請假效益 / 飛行時長 / 策略風險。

- 將各候選 plan 的四個維度做 **min-max 正規化** (0 = 最差, 1 = 最佳)。
- 以使用者提供的權重做加權總和（權重自動 L1 正規化）。
- 將分數寫回 ``StrategyPlan.score``；回傳同一 list（已排序）。

此設計刻意保持 pure function + 無 I/O，方便於單元測試與未來做離線 A/B 比較。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from app.schemas.itinerary import ScoringWeights
from app.services.strategies.base import RiskLevel, StrategyPlan


_RISK_WEIGHT = {RiskLevel.LOW: 0.1, RiskLevel.MEDIUM: 0.4, RiskLevel.HIGH: 1.0}

# A plan's "飛行時長" proxy — number of legs across all tickets (lower = better).
# We avoid pulling actual durations here so stub / live providers can skip
# computing them when they are unknown.


def score_plans(
    plans: Iterable[StrategyPlan],
    *,
    weights: ScoringWeights | None = None,
    pto_days_used: int | None = None,
) -> list[StrategyPlan]:
    plans = list(plans)
    if not plans:
        return plans

    w = weights or ScoringWeights()
    w_total = w.price + w.pto_efficiency + w.flight_time + w.strategy_risk or 1.0
    weights_norm = (
        w.price / w_total,
        w.pto_efficiency / w_total,
        w.flight_time / w_total,
        w.strategy_risk / w_total,
    )

    prices = [p.total_cost for p in plans]
    flight_steps = [sum(len(t.legs) for t in p.tickets) for p in plans]
    pto_eff = [
        p.total_travel_days / max(pto_days_used or p.pto_days or 1, 1)
        for p in plans
    ]
    risks = [_risk_score(p) for p in plans]

    def _mm(values: list[float], *, inverse: bool) -> list[float]:
        lo, hi = min(values), max(values)
        if hi == lo:
            return [1.0] * len(values)
        if inverse:
            return [(hi - v) / (hi - lo) for v in values]
        return [(v - lo) / (hi - lo) for v in values]

    s_price = _mm(prices, inverse=True)
    s_flight = _mm(flight_steps, inverse=True)
    s_pto = _mm(pto_eff, inverse=False)
    s_risk = _mm(risks, inverse=True)

    wp, wpto, wf, wr = weights_norm
    scored: list[StrategyPlan] = []
    for i, p in enumerate(plans):
        s = wp * s_price[i] + wpto * s_pto[i] + wf * s_flight[i] + wr * s_risk[i]
        scored.append(replace(p, score=round(s, 4)))
    scored.sort(key=lambda p: p.score or 0.0, reverse=True)
    return scored


def _risk_score(plan: StrategyPlan) -> float:
    if not plan.warnings:
        return 0.0
    return sum(_RISK_WEIGHT[w.level] for w in plan.warnings)
