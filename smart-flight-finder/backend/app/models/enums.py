"""Shared enum types used by the ORM, Pydantic schemas, and services."""

from enum import StrEnum


class TripType(StrEnum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"
    MULTI_CITY = "multi_city"


class CabinClass(StrEnum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class TicketStrategyType(StrEnum):
    """進階票規策略類型。

    - ``STANDARD``        : 傳統點對點來回/單程/多段。
    - ``OPEN_JAW``        : 不同進出點 (A→B，C→A)。
    - ``REVERSE``         : 反向開票 / 倒置票 (B→A→B 比 A→B→A 便宜時的套票)。
    - ``BACK_TO_BACK_4LEG``: 外站四段票 (XMN-TPE-NRT-TPE-XMN 類結構)。
    - ``HIDDEN_CITY``     : 隱藏城市 / Skiplagging — 旅客於中轉點棄程。
    """

    STANDARD = "standard"
    OPEN_JAW = "open_jaw"
    REVERSE = "reverse"
    BACK_TO_BACK_4LEG = "back_to_back_4leg"
    HIDDEN_CITY = "hidden_city"


class DateWindowRole(StrEnum):
    """DateWindow 綁定到行程中的哪一段。"""

    OUTBOUND = "outbound"
    RETURN = "return"
    SEGMENT = "segment"  # Multi-city intermediate segment


class HolidayType(StrEnum):
    """台灣行政院人事總處假日分類。"""

    NATIONAL = "national"              # 國定假日 (例：元旦、228、國慶)
    LUNAR = "lunar"                    # 農曆節日 (例：春節、端午、中秋)
    MEMORIAL = "memorial"              # 紀念日 (例：清明)
    MAKEUP_WORKDAY = "makeup_workday"  # 補班日 (-1 平衡調整)
    OBSERVED = "observed"              # 補假 / 連假延伸
