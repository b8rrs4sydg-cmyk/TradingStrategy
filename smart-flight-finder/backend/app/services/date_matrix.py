"""彈性日期矩陣展開引擎 (Phase 2 core)。

輸入一組 ``DateWindow``，展開成具體候選日期；對於整個行程，再組合跨視窗的
日期配對 — 這是後續策略引擎的輸入。

主要 API：
- :func:`expand_window`      — 單一視窗展開
- :func:`expand_itinerary`   — 一次請求的所有視窗展開 (round-trip / multi-city)
- :func:`iter_date_combos`   — 跨視窗笛卡兒積，含「回程不早於去程」等合法性剪枝
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from app.models.enums import DateWindowRole, TripType
from app.schemas.itinerary import DateWindowIn, ItineraryRequestIn


@dataclass(frozen=True, slots=True)
class ExpandedWindow:
    role: DateWindowRole
    sequence: int
    anchor_date: date
    candidates: tuple[date, ...]
    segment_origin: str | None = None
    segment_destination: str | None = None


def expand_window(w: DateWindowIn) -> ExpandedWindow:
    """Expand a single ``DateWindow`` into concrete candidate dates."""

    start = w.anchor_date - timedelta(days=w.flex_before)
    end = w.anchor_date + timedelta(days=w.flex_after)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    if w.allow_weekend_only:
        days = [d for d in days if d.weekday() >= 5]

    return ExpandedWindow(
        role=w.role,
        sequence=w.sequence,
        anchor_date=w.anchor_date,
        candidates=tuple(days),
        segment_origin=w.segment_origin,
        segment_destination=w.segment_destination,
    )


def expand_itinerary(req: ItineraryRequestIn) -> list[ExpandedWindow]:
    """Expand every window in a request, keeping sequence order stable."""

    return [
        expand_window(w)
        for w in sorted(req.date_windows, key=lambda w: (w.sequence, w.role.value))
    ]


def iter_date_combos(
    expanded: Iterable[ExpandedWindow],
    *,
    trip_type: TripType,
    min_days_abroad: int = 1,
    max_days_abroad: int | None = None,
) -> Iterator[tuple[date, ...]]:
    """笛卡兒積後，依 trip_type 做合法性剪枝。

    * round_trip  : 回程 ≥ 去程 + ``min_days_abroad``；若指定 ``max_days_abroad`` 再夾上限。
    * multi_city  : 相鄰視窗需嚴格遞增 (段 N+1 的候選日 > 段 N)。
    * one_way     : 不剪枝。

    每個 tuple 的順序與 ``expanded`` 相同。
    """

    windows = list(expanded)
    if not windows:
        return

    out_i = next((i for i, w in enumerate(windows) if w.role is DateWindowRole.OUTBOUND), None)
    ret_i = next((i for i, w in enumerate(windows) if w.role is DateWindowRole.RETURN), None)
    check_pair = trip_type is TripType.ROUND_TRIP and out_i is not None and ret_i is not None

    def ok_prefix(prefix: tuple[date, ...]) -> bool:
        """False as soon as the dates chosen so far already break an ordering rule: the whole subtree is skipped
        instead of being built by the cartesian product and filtered afterwards."""

        n = len(prefix)
        if trip_type is TripType.MULTI_CITY and n >= 2 and prefix[-2] >= prefix[-1]:
            return False
        if check_pair and max(out_i, ret_i) < n:
            gap = (prefix[ret_i] - prefix[out_i]).days
            if gap < min_days_abroad or (max_days_abroad is not None and gap > max_days_abroad):
                return False
        return True

    def walk(prefix: tuple[date, ...]) -> Iterator[tuple[date, ...]]:
        if len(prefix) == len(windows):
            yield prefix
            return
        for c in windows[len(prefix)].candidates:
            nxt = (*prefix, c)
            if ok_prefix(nxt):
                yield from walk(nxt)

    yield from walk(())


def matrix_cardinality(expanded: Iterable[ExpandedWindow]) -> int:
    """Pre-expansion cardinality (upper bound on combinations before pruning)."""

    total = 1
    for w in expanded:
        total *= max(1, len(w.candidates))
    return total
