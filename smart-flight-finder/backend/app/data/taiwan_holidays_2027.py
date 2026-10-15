"""2027 台灣連假靜態資料 (seed data).

⚠️  **重要**：行政院人事行政總處 (DGPA) 通常於前一年中下旬公告下一年度假期。
   本檔案為 Phase 1 開發用近似資料 (以已知農曆/國定日期推估)，
   正式上線前請以 DGPA 公告為準並更新 ``verified_source`` 欄位。
   來源範例：https://www.dgpa.gov.tw/

資料結構：
- ``HOLIDAYS``        : list[HolidayRecord] — 每一個官方假日/補班日。
- ``LEAVE_STRATEGIES``: list[LeaveStrategyRecord] — 「請 N 休 M」組合。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models.enums import HolidayType


@dataclass(frozen=True, slots=True)
class HolidayRecord:
    day: date
    name_zh: str
    name_en: str
    kind: HolidayType
    is_workday: bool = False
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class LeaveStrategyRecord:
    holiday_key: str
    label_zh: str
    pto_days: int
    total_days: int
    window_start: date
    window_end: date
    description: str | None = None


# ---------------------------------------------------------------------------
# 2027 台灣國定假日 (近似值 — 正式公告請以 DGPA 為準)
# ---------------------------------------------------------------------------
HOLIDAYS: list[HolidayRecord] = [
    # 元旦連假
    HolidayRecord(date(2027, 1, 1), "開國紀念日 (元旦)", "New Year's Day", HolidayType.NATIONAL),

    # 春節 (農曆正月初一 = 2027-02-06 週六)
    HolidayRecord(date(2027, 2, 5), "小年夜 (補休)", "Lunar New Year's Eve Eve", HolidayType.OBSERVED,
                  notes="若 DGPA 公告為補假，以公告為準"),
    HolidayRecord(date(2027, 2, 6), "除夕", "Lunar New Year's Eve", HolidayType.LUNAR),
    HolidayRecord(date(2027, 2, 7), "春節初一", "Lunar New Year Day 1", HolidayType.LUNAR),
    HolidayRecord(date(2027, 2, 8), "春節初二", "Lunar New Year Day 2", HolidayType.LUNAR),
    HolidayRecord(date(2027, 2, 9), "春節初三", "Lunar New Year Day 3", HolidayType.LUNAR),
    HolidayRecord(date(2027, 2, 10), "春節補假", "Lunar New Year Observed", HolidayType.OBSERVED,
                  notes="週六/日農曆年補假"),
    HolidayRecord(date(2027, 2, 11), "春節補假", "Lunar New Year Observed", HolidayType.OBSERVED,
                  notes="若 DGPA 公告調整，以公告為準"),

    # 228 和平紀念日 (2027-02-28 週日 → 隔日補假 3/1)
    HolidayRecord(date(2027, 2, 28), "和平紀念日", "Peace Memorial Day", HolidayType.NATIONAL),
    HolidayRecord(date(2027, 3, 1), "和平紀念日補假", "Peace Memorial Day Observed", HolidayType.OBSERVED),

    # 兒童節 / 清明 (2027 兒童節 4/4 週日、清明 4/5 週一)
    HolidayRecord(date(2027, 4, 4), "兒童節", "Children's Day", HolidayType.NATIONAL,
                  notes="2027-04-04 週日"),
    HolidayRecord(date(2027, 4, 5), "清明節", "Tomb Sweeping Day", HolidayType.MEMORIAL),
    HolidayRecord(date(2027, 4, 6), "兒童節補假", "Children's Day Observed", HolidayType.OBSERVED),

    # 勞動節 (2027-05-01 週六 → 4/30 補假, 僅勞工適用；此處一併列入)
    HolidayRecord(date(2027, 4, 30), "勞動節補假", "Labor Day Observed", HolidayType.OBSERVED,
                  notes="僅適用勞基法勞工"),
    HolidayRecord(date(2027, 5, 1), "勞動節", "Labor Day", HolidayType.NATIONAL,
                  notes="僅適用勞基法勞工"),

    # 端午節 (農曆五月初五 = 2027-06-09 週三)
    HolidayRecord(date(2027, 6, 9), "端午節", "Dragon Boat Festival", HolidayType.LUNAR),

    # 中秋節 (農曆八月十五 ≈ 2027-09-15 週三)
    HolidayRecord(date(2027, 9, 15), "中秋節", "Mid-Autumn Festival", HolidayType.LUNAR),

    # 國慶日 (2027-10-10 週日 → 10/11 補假)
    HolidayRecord(date(2027, 10, 10), "國慶日", "National Day", HolidayType.NATIONAL),
    HolidayRecord(date(2027, 10, 11), "國慶日補假", "National Day Observed", HolidayType.OBSERVED),
]


# ---------------------------------------------------------------------------
# 2027 請假攻略 — 「請 N 天特休，換得連續 M 天假期」
# ---------------------------------------------------------------------------
# 命名規則 (holiday_key)：
#   nyd        = 元旦
#   lunar_ny   = 春節
#   peace228   = 和平紀念日
#   qingming   = 清明/兒童節
#   labor      = 勞動節
#   duanwu     = 端午節
#   midautumn  = 中秋節
#   national   = 國慶日
# ---------------------------------------------------------------------------
LEAVE_STRATEGIES: list[LeaveStrategyRecord] = [
    LeaveStrategyRecord(
        holiday_key="lunar_ny",
        label_zh="春節請 2 休 11",
        pto_days=2,
        total_days=11,
        window_start=date(2027, 2, 5),
        window_end=date(2027, 2, 15),
        description="春節連假週六起，請 2/12(五) + 2/15(一) 共 2 天即可休 11 天。",
    ),
    LeaveStrategyRecord(
        holiday_key="peace228",
        label_zh="228 請 1 休 4",
        pto_days=1,
        total_days=4,
        window_start=date(2027, 2, 26),
        window_end=date(2027, 3, 1),
        description="請 2/26(五) 搭配 2/27(六)、2/28(日)、3/1(一) 補假。",
    ),
    LeaveStrategyRecord(
        holiday_key="qingming",
        label_zh="清明請 3 休 9",
        pto_days=3,
        total_days=9,
        window_start=date(2027, 4, 3),
        window_end=date(2027, 4, 11),
        description="請 4/7-4/9 共 3 天可連休至 4/11(日)。",
    ),
    LeaveStrategyRecord(
        holiday_key="labor",
        label_zh="勞動節請 1 休 4",
        pto_days=1,
        total_days=4,
        window_start=date(2027, 4, 29),
        window_end=date(2027, 5, 2),
        description="請 4/29(四) 可連休至 5/2(日)。",
    ),
    LeaveStrategyRecord(
        holiday_key="duanwu",
        label_zh="端午請 2 休 5",
        pto_days=2,
        total_days=5,
        window_start=date(2027, 6, 9),
        window_end=date(2027, 6, 13),
        description="端午 6/9(三)，請 6/10-6/11 共 2 天可連休至 6/13(日)。",
    ),
    LeaveStrategyRecord(
        holiday_key="midautumn",
        label_zh="中秋請 2 休 5",
        pto_days=2,
        total_days=5,
        window_start=date(2027, 9, 15),
        window_end=date(2027, 9, 19),
        description="中秋 9/15(三)，請 9/16-9/17 共 2 天可連休至 9/19(日)。",
    ),
    LeaveStrategyRecord(
        holiday_key="national",
        label_zh="國慶請 4 休 9",
        pto_days=4,
        total_days=9,
        window_start=date(2027, 10, 9),
        window_end=date(2027, 10, 17),
        description="國慶 10/10(日)、補假 10/11(一)，請 10/12-10/15 共 4 天可連休至 10/17(日)。",
    ),
]


verified_source: str | None = None  # 當 DGPA 公告釋出後，填入來源 URL


def summary() -> str:
    """Human-readable summary used by seed CLI."""
    return (
        f"2027 TW holidays: {len(HOLIDAYS)} rows, "
        f"leave strategies: {len(LEAVE_STRATEGIES)} rows. "
        f"verified_source={verified_source!r}"
    )
