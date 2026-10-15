"""Minimum Connection Time 政策與檢查器。

四段票 (back-to-back) 關鍵風險之一是：兩張票互為獨立 PNR，意味著
行李不會直掛、必須入境再出境、重新 check-in — 所以我們拉開比
一般同票轉機更長的「安全緩衝」。

此模組的門檻值為可調整的保守預設；真實上線時可做成資料表供營運調整。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.services.strategies.base import (
    FlightLeg,
    RiskLevel,
    RiskWarning,
    TicketOffer,
)


@dataclass(frozen=True, slots=True)
class MctPolicy:
    """每個轉機類型的最小安全緩衝 (minutes)。"""

    same_ticket_domestic: int = 45
    same_ticket_international: int = 90
    #
    # Separate-ticket connections — passenger must claim/recheck bags and
    # pass immigration twice (arrival + re-departure). Taipei (TPE)
    # typically needs 2.5–3.5h to be safe during normal hours.
    separate_ticket_domestic: int = 150
    separate_ticket_international: int = 210

    def required_minutes(self, *, cross_ticket: bool, international: bool) -> int:
        if cross_ticket:
            return (
                self.separate_ticket_international
                if international
                else self.separate_ticket_domestic
            )
        return (
            self.same_ticket_international
            if international
            else self.same_ticket_domestic
        )


DEFAULT_MCT = MctPolicy()


def _is_international(a: FlightLeg, b: FlightLeg) -> bool:
    """Heuristic: any non-Taiwan airport implies the connection crosses borders.

    IATA 3-letter codes beginning with ``T`` + Taiwan carriers are a weak signal;
    for Phase 2 we treat as international whenever the pair's airports differ in
    country, approximated by comparing against a small Taiwan airport whitelist.
    """

    tw_airports = {"TPE", "TSA", "KHH", "RMQ", "TNN", "HUN", "KNH", "MZG", "TTT", "HCN"}
    return not (a.destination in tw_airports and b.origin in tw_airports)


def check_connection(
    arriving: FlightLeg,
    departing: FlightLeg,
    *,
    cross_ticket: bool,
    policy: MctPolicy = DEFAULT_MCT,
) -> RiskWarning | None:
    """Return a :class:`RiskWarning` if the layover violates the MCT policy."""

    if arriving.destination != departing.origin:
        return RiskWarning(
            level=RiskLevel.HIGH,
            code="connection_airport_mismatch",
            message=(
                f"轉機機場不一致：{arriving.destination} 下機 vs "
                f"{departing.origin} 登機"
            ),
        )

    gap = departing.departure - arriving.arrival
    required = policy.required_minutes(
        cross_ticket=cross_ticket,
        international=_is_international(arriving, departing),
    )
    required_td = timedelta(minutes=required)

    if gap < timedelta(0):
        return RiskWarning(
            level=RiskLevel.HIGH,
            code="mct_negative_overlap",
            message=f"航段重疊 {-gap} — 下一班於上一班落地前起飛",
        )
    if gap < required_td:
        return RiskWarning(
            level=RiskLevel.HIGH,
            code="mct_too_tight",
            message=(
                f"轉機時間 {_fmt(gap)} 低於建議 {required} 分鐘"
                f" ({'跨票' if cross_ticket else '同票'})"
            ),
        )
    if gap < required_td + timedelta(minutes=30):
        return RiskWarning(
            level=RiskLevel.MEDIUM,
            code="mct_marginal",
            message=f"轉機時間 {_fmt(gap)} 接近 {required} 分鐘下限，建議再加 30 分鐘緩衝",
        )
    return None


def check_cross_ticket_handoff(
    inbound_ticket: TicketOffer,
    outbound_ticket: TicketOffer,
    *,
    policy: MctPolicy = DEFAULT_MCT,
) -> list[RiskWarning]:
    """Validate the junction between two separate tickets.

    Returns an empty list if the handoff is safe; otherwise one or more warnings.
    """

    warnings: list[RiskWarning] = []
    arrival_leg = inbound_ticket.last_leg()
    departure_leg = outbound_ticket.first_leg()
    w = check_connection(
        arrival_leg, departure_leg, cross_ticket=True, policy=policy
    )
    if w:
        warnings.append(w)

    if (
        inbound_ticket.baggage_through_checked is False
        or outbound_ticket.baggage_through_checked is False
    ):
        warnings.append(
            RiskWarning(
                level=RiskLevel.MEDIUM,
                code="baggage_recheck_required",
                message="跨票行李無法直掛，需入境提領後重新 check-in",
            )
        )
    return warnings


def _fmt(td: timedelta) -> str:
    total_min = int(td.total_seconds() // 60)
    h, m = divmod(total_min, 60)
    return f"{h}h{m:02d}m"
