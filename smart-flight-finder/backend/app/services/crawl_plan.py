"""What the fare crawler fetches, and in which order.

1. The planners (標準來回 / 反向票＋倒買法 / 外站四腿票) run once against a
   :class:`RecordingProvider`, which yields every query they can make for
   the configured scenario — no hand-written list to drift from the code.
2. Stage 1: all one-way and round-trip searches (Google answers these in
   ~2 s). They are the baselines every two-trip plan must beat.
3. Stage 2: multi-city searches are slow (~15 s) and numerous, so they are
   ranked with the REAL stage-1 prices. For a 四腿票 X→TPE→D→TPE→Y the
   *budget* is what the ticket may cost and still save money::

       budget = rt(TPE⇄D, trip A) + rt(TPE⇄Y, trip B) − ow(TPE→X) − ow(Y→TPE)

   Combinations whose budget leaves less than ``PROMISING`` of the trip-A
   round trip are fetched once (so the best non-saving plan can still be
   shown); promising ones get up to ``PER_GROUP`` date variants, all within
   ``max_multi_city``. Open-jaw 倒買法 tickets are ranked by the price of
   their mirrored round trip on the same dates.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from app.data.taiwan_holidays_2027 import LEAVE_STRATEGIES
from app.models.enums import TicketStrategyType, TripType
from app.providers.google_flights import GOOGLE_HORIZON_DAYS, fare_key, parse_key
from app.providers.recording import RecordingProvider
from app.schemas.itinerary import CandidateWindowIn, ItineraryRequestIn
from app.services.search import SearchService

PROMISING = 0.8   # four-leg budget ≥ 80% of the trip-A round trip
PER_GROUP = 3     # date variants per promising multi-city combination


@dataclass
class CrawlConfig:
    origins: list[str] = field(default_factory=lambda: ["TPE"])
    destinations: list[str] = field(default_factory=lambda: ["NRT", "KIX", "ICN", "BKK", "LHR"])
    outer_stations: list[str] = field(default_factory=lambda: ["HKG", "ICN", "BKK"])
    holidays: list[str] = field(default_factory=lambda: ["lunar_ny", "qingming", "duanwu"])
    flex: int = 1

    def as_dict(self) -> dict:
        return asdict(self)


def build_request(cfg: CrawlConfig, *, today: date) -> ItineraryRequestIn:
    horizon = today + timedelta(days=GOOGLE_HORIZON_DAYS)
    windows = [
        CandidateWindowIn(
            holiday_key=s.holiday_key,
            depart=s.window_start,
            return_date=s.window_end,
            depart_flex=cfg.flex,
            return_flex=cfg.flex,
        )
        for s in LEAVE_STRATEGIES
        if s.holiday_key in cfg.holidays
        and today < s.window_start - timedelta(days=cfg.flex)
        and s.window_end + timedelta(days=cfg.flex) <= horizon
    ]
    return ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP,
        origins=cfg.origins,
        destinations=cfg.destinations,
        strategies=[
            TicketStrategyType.STANDARD,
            TicketStrategyType.REVERSE,
            TicketStrategyType.BACK_TO_BACK_4LEG,
        ],
        back_to_back_outer_stations=cfg.outer_stations,
        candidate_windows=windows,
    )


def planner_queries(cfg: CrawlConfig, *, today: date) -> list[str]:
    """Every query the planners make for ``cfg`` within Google's horizon."""

    rec = RecordingProvider()
    SearchService(rec).run(build_request(cfg, today=today))
    horizon = today + timedelta(days=GOOGLE_HORIZON_DAYS)
    return [k for k in rec.keys if all(today < d <= horizon for _, _, d in parse_key(k)[1])]


def split_stages(keys: Sequence[str]) -> tuple[list[str], list[str]]:
    return [k for k in keys if not k.startswith("mc|")], [k for k in keys if k.startswith("mc|")]


# --- stage 2 ranking ----------------------------------------------------------
def _min_price(prices: Mapping[str, int], prefix: str, ok) -> int | None:
    vals = [p for k, p in prices.items() if k.startswith(prefix) and ok(k)]
    return min(vals) if vals else None


def _near(day: date, flex: int):
    def ok(key: str) -> bool:
        return abs((parse_key(key)[1][0][2] - day).days) <= flex + 1

    return ok


def four_leg_budget(key: str, prices: Mapping[str, int], cfg: CrawlConfig) -> tuple[float | None, tuple]:
    """(room for saving / trip-Q round trip, group) for a 四腿票 key.

    The four-leg ticket replaces three round trips (X on P, D on Q, Y on R);
    the 單買初段 and 最後一段 are bought separately, so what it may cost at most
    to beat them is rt(X) + rt(D) + rt(Y) − ow(TPE→X) − ow(Y→TPE).
    """

    _, segs = parse_key(key)
    (x, _, c1), (_, d, c2), _, (_, y, r_dep) = segs
    group = ("4leg", x, d, y, c1.month, c2.month, r_dep.month)
    ow_first = _min_price(prices, f"ow|TPE|{x}|", lambda k: parse_key(k)[1][0][2] < c1)
    ow_last = _min_price(prices, f"ow|{y}|TPE|", lambda k: parse_key(k)[1][0][2] > r_dep)
    rt_x = _min_price(prices, f"rt|TPE|{x}|", lambda k: abs((parse_key(k)[1][1][2] - c1).days) <= cfg.flex + 1)
    rt_d = _min_price(prices, f"rt|TPE|{d}|", _near(c2, cfg.flex))
    rt_y = _min_price(prices, f"rt|TPE|{y}|", _near(r_dep, cfg.flex))
    if None in (ow_first, ow_last, rt_x, rt_d, rt_y):
        return None, group
    return (rt_x + rt_d + rt_y - ow_first - ow_last) / max(rt_d, 1), group


def open_jaw_score(key: str, prices: Mapping[str, int]) -> tuple[float | None, tuple]:
    """(−mirrored round-trip price, group) for a two-segment open-jaw key.

    包覆票 H→A_in … B_out→H mirrors rt H⇄A_in; 反向票 A_out→H … H→B_in
    mirrors rt A_out⇄H — either way the round trip on the first segment.
    """

    _, ((o1, d1, day1), (o2, d2, day2)) = parse_key(key)
    group = ("oj", o1, d1, o2, d2, day1.month, day2.month)
    p = prices.get(fare_key([(o1, d1, day1), (d1, o1, day2)], round_trip=True))
    return (None if p is None else -p), group


def rank_multi_city(
    mc_keys: Sequence[str], prices: Mapping[str, int], cfg: CrawlConfig, *, max_multi_city: int
) -> list[str]:
    groups: dict[tuple, list[tuple[float, str]]] = defaultdict(list)
    for key in mc_keys:
        four = len(parse_key(key)[1]) == 4
        score, group = four_leg_budget(key, prices, cfg) if four else open_jaw_score(key, prices)
        groups[group].append((float("-inf") if score is None else score, key))
    picked: list[tuple[float, str]] = []
    for group, items in groups.items():
        items.sort(reverse=True)
        if group[0] == "4leg":
            k = PER_GROUP if items[0][0] >= PROMISING else 1
        else:
            k = 2
        picked += items[:k]
    picked.sort(reverse=True)  # most promising first, so the cap drops the weakest
    return [key for _, key in picked[:max_multi_city]]
