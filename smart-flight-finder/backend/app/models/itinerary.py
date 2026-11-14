"""Phase 1 核心資料模型：ItineraryRequest / DateWindow / TicketStrategy。

資料關係：
- ``ItineraryRequest`` 代表一次使用者送出的搜尋需求。
- 一個請求可包含多個 ``DateWindow`` (去程/回程/多段)，每個視窗有自己的 ±N 彈性。
- 一個請求允許勾選多種 ``TicketStrategyType`` 讓策略引擎並行評估。

Phase 1 僅建結構；Phase 2 開始填入搜尋邏輯。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import CabinClass, DateWindowRole, TicketStrategyType, TripType


class ItineraryRequest(Base):
    """一次完整的搜尋需求 (持久化後可供歷史查詢與重跑)。"""

    __tablename__ = "itinerary_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )

    # Who / for whom
    user_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)

    # Trip shape
    trip_type: Mapped[TripType] = mapped_column(String(16))
    cabin: Mapped[CabinClass] = mapped_column(String(24), default=CabinClass.ECONOMY)
    adults: Mapped[int] = mapped_column(Integer, default=1)
    children: Mapped[int] = mapped_column(Integer, default=0)
    infants: Mapped[int] = mapped_column(Integer, default=0)

    # Origin / destination lists
    #   origins:      e.g. ["TPE", "TSA", "KHH"] — 可多個台灣出發機場
    #   destinations: e.g. ["NRT", "HND", "KIX", "ICN"] 或 ["JP", "KR"] 國家層級
    origins: Mapped[list[str]] = mapped_column(JSON, default=list)
    destinations: Mapped[list[str]] = mapped_column(JSON, default=list)

    # 選擇哪些票規策略並行評估
    strategies: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: [TicketStrategyType.STANDARD.value]
    )

    # 選定的 2027 連假 key (optional)；None 代表自定義日期
    holiday_key: Mapped[str | None] = mapped_column(String(32), default=None, index=True)

    # Economic constraints
    max_total_budget: Mapped[int | None] = mapped_column(Integer, default=None)  # TWD
    max_pto_days: Mapped[int | None] = mapped_column(Integer, default=None)

    # 自訂評分權重 (總和應為 1.0；若為 None 則用系統預設)
    scoring_weights: Mapped[dict | None] = mapped_column(JSON, default=None)

    date_windows: Mapped[list[DateWindow]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="DateWindow.sequence",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ItineraryRequest id={self.id} {self.trip_type} "
            f"{self.origins}->{self.destinations} strategies={self.strategies}>"
        )


class DateWindow(Base):
    """彈性日期視窗：以 ``anchor_date`` 為中心，前後各開 ±N 天的日期矩陣。

    Example — 去程以 2027-02-05 為中心，前 ±2 天、後 ±2 天：
        anchor_date = 2027-02-05, flex_before = 2, flex_after = 2
    會展開為 2027-02-03..2027-02-07 五個候選日期。
    """

    __tablename__ = "date_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("itinerary_requests.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0)  # multi-city segment order
    role: Mapped[DateWindowRole] = mapped_column(String(16))

    anchor_date: Mapped[date] = mapped_column(Date)
    flex_before: Mapped[int] = mapped_column(Integer, default=0)
    flex_after: Mapped[int] = mapped_column(Integer, default=0)
    allow_weekend_only: Mapped[bool] = mapped_column(default=False)

    # 針對多段旅程此視窗專屬的 origin / destination (覆蓋請求層的大範圍)
    segment_origin: Mapped[str | None] = mapped_column(String(8), default=None)
    segment_destination: Mapped[str | None] = mapped_column(String(8), default=None)

    request: Mapped[ItineraryRequest] = relationship(back_populates="date_windows")

    @property
    def total_candidate_days(self) -> int:
        """展開後的候選日期數量 (含 anchor)。"""
        return self.flex_before + self.flex_after + 1

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DateWindow {self.role} anchor={self.anchor_date} "
            f"±({self.flex_before},{self.flex_after})>"
        )
