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
4. One-way screening of 四腿票: a multi-city fare is never below the sum of its
   one-way legs (lowest ratio 1.04 for two legs, 1.26 for four over 70 real
   fares, ``scripts/exp_mc_vs_ow.py``), and the legs are cheap, fast and
   shared by thousands of combinations. So the legs' one-way fares go into
   stage 1 (:func:`with_leg_keys`) and a four-leg combination whose floor
   already exceeds its budget is not fetched as a multi-city query at all
   (:func:`screen_four_leg`); the few closest calls are still fetched to
   keep checking the bound.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from app.data.metro import route_key
from app.data.taiwan_holidays_2027 import LEAVE_STRATEGIES
from app.models.enums import TicketStrategyType, TripType
from app.providers.google_flights import GOOGLE_HORIZON_DAYS, fare_key, parse_key
from app.schemas.itinerary import CandidateWindowIn, ItineraryRequestIn
from app.services.query_plan import four_leg_room_for, required_queries
from app.services.search import SearchService

PROMISING = 0.8  # four-leg budget ≥ 80% of the trip-A round trip
PER_GROUP = 3  # date variants per promising multi-city combination
SCREEN_FACTOR = 0.95  # floor = this share of the sum of the legs' one-way fares (only used when screening is switched on)
# Screening on the one-way sum is OFF by default (SCREEN_ONE_WAY=1 turns it on): it pruned a four-leg ticket that does beat three
# round trips. Stage 2 is still capped and ranked by the saving room (rank_multi_city), which does not rely on that premise.
SCREEN_ONE_WAY = os.getenv("SCREEN_ONE_WAY", "0") == "1"
SCREEN_AUDIT = 10  # closest pruned combinations that are fetched anyway


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

    keys = required_queries(lambda rec: SearchService(rec).run(build_request(cfg, today=today)))
    horizon = today + timedelta(days=GOOGLE_HORIZON_DAYS)
    return [k for k in keys if all(today < d <= horizon for _, _, d in parse_key(k)[1])]


def split_stages(keys: Sequence[str]) -> tuple[list[str], list[str]]:
    return [k for k in keys if not k.startswith("mc|")], [k for k in keys if k.startswith("mc|")]


# --- stage 2 ranking ----------------------------------------------------------
def four_leg_room(
    key: str, prices: Mapping[str, int], cfg: CrawlConfig
) -> tuple[float | None, int | None, tuple]:
    """(money the four-leg ticket may cost and still save, trip-Q round trip, group) for a 四腿票 key.

    The four-leg ticket replaces three round trips (X on P, D on Q, Y on R);
    the 單買初段 and 最後一段 are bought separately, so what it may cost at most
    to beat them is rt(X) + rt(D) + rt(Y) − ow(TPE→X) − ow(Y→TPE).
    """

    return four_leg_room_for(key, prices, cfg.flex)


def four_leg_budget(
    key: str, prices: Mapping[str, int], cfg: CrawlConfig
) -> tuple[float | None, tuple]:
    """(room for saving / trip-Q round trip, group) for a 四腿票 key."""

    room, rt_d, group = four_leg_room(key, prices, cfg)
    return (None if room is None else room / max(rt_d or 1, 1)), group


# --- one-way screening ----------------------------------------------------------
def leg_keys(key: str) -> list[str]:
    """The one-way query of every segment of a multi-city key."""

    return [fare_key([seg], round_trip=False) for seg in parse_key(key)[1]]


def with_leg_keys(stage1: Sequence[str], mc_keys: Sequence[str]) -> list[str]:
    """``stage1`` plus the one-way legs of every four-leg candidate (each leg once)."""

    have = set(stage1)
    out = list(stage1)
    for key in mc_keys:
        if len(parse_key(key)[1]) != 4:
            continue
        for leg in leg_keys(key):
            if leg not in have:
                have.add(leg)
                out.append(leg)
    return out


def one_way_floor(key: str, prices: Mapping[str, int]) -> float | None:
    legs = [prices.get(k) for k in leg_keys(key)]
    return None if None in legs else SCREEN_FACTOR * sum(legs)


def screen_four_leg(
    mc_keys: Sequence[str],
    prices: Mapping[str, int],
    cfg: CrawlConfig,
    *,
    drop_unknown: bool = False,
    audit: int = SCREEN_AUDIT,
    enabled: bool | None = None,
) -> tuple[list[str], list[str], int]:
    """(keys worth fetching, audit keys, how many were left out).

    A four-leg key is pruned when its one-way floor already reaches the money
    it may cost to save (:func:`four_leg_room`). A key whose legs are unknown is
    kept, or dropped with ``drop_unknown`` (only for a caller that KNOWS Google has no
    flight on one of the legs: a leg that merely failed to load is just as absent from
    ``prices``, so the crawl scripts keep such keys). The ``audit`` closest calls among
    the pruned keys come back separately: the caller must fetch them AFTER
    ``rank_multi_city``, which would drop them (their budgets are the lowest) and leave the
    bound untested. Two-segment keys are not screened (a pair of them forms a plan).
    """

    if not (SCREEN_ONE_WAY if enabled is None else enabled):
        return list(mc_keys), [], 0
    kept: list[str] = []
    pruned: list[tuple[float, str]] = []
    for key in mc_keys:
        if len(parse_key(key)[1]) != 4:
            kept.append(key)
            continue
        room, _, _ = four_leg_room(key, prices, cfg)
        floor = one_way_floor(key, prices)
        if floor is None:
            if not drop_unknown:
                kept.append(key)
            continue
        if room is None or floor < room:
            kept.append(key)
        else:
            pruned.append((floor / max(room, 1), key))
    pruned.sort()
    sample = [key for _, key in pruned[:audit]]
    return kept, sample, len(pruned) - len(sample)


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
    mc_keys: Sequence[str],
    prices: Mapping[str, int],
    cfg: CrawlConfig,
    *,
    max_multi_city: int,
    carriers: CarrierNetwork | None = None,
) -> list[str]:
    """The multi-city keys worth the stage-2 budget, most promising first.

    ``carriers`` (optional) adds :data:`NETWORK_BONUS` to a four-leg combination that ONE airline is known to fly end to end:
    only such a combination can be sold as a single through fare. It only reorders; nothing is dropped for lacking it.
    """

    groups: dict[tuple, list[tuple[float, str]]] = defaultdict(list)
    for key in mc_keys:
        four = len(parse_key(key)[1]) == 4
        score, group = four_leg_budget(key, prices, cfg) if four else open_jaw_score(key, prices)
        if score is not None and four and carriers is not None:
            score += carriers.bonus(key)
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


def four_leg_hits(fetched: Mapping[str, dict], prices: Mapping[str, int], cfg: CrawlConfig) -> tuple[int, int]:
    """(four-leg tickets priced this run that cost less than the saving room, four-leg tickets priced). The hit rate is the
    number to watch when changing what stage 2 asks for."""

    priced = hits = 0
    for key, entry in fetched.items():
        if not key.startswith("mc|") or len(parse_key(key)[1]) != 4 or not entry.get("price"):
            continue
        room, _, _ = four_leg_room(key, prices, cfg)
        if room is None:
            continue
        priced += 1
        hits += entry["price"] < room
    return hits, priced


# --- which airline flies what (from the fares already priced) ------------------------------------------------------------
NETWORK_BONUS = 0.3  # added to a combination's saving room when ONE airline is known to fly every leg of it


class CarrierNetwork:
    """Airlines seen selling a single-airline fare on a route (metro-normalised, direction-free), from ``by_airline`` of every
    ow / rt / mc entry. Only a ranking hint: a route with no data is unknown, never "not flown"."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], set[str]] = defaultdict(set)

    @classmethod
    def from_fares(cls, fares: Mapping[str, dict]) -> CarrierNetwork:
        net = cls()
        for key, entry in fares.items():
            airlines = entry.get("by_airline")
            if not airlines:
                continue
            for o, d, _ in parse_key(key)[1]:
                a, b = route_key(o), route_key(d)
                net.routes[(a, b) if a <= b else (b, a)].update(airlines)
        return net

    def serving(self, origin: str, dest: str) -> set[str]:
        a, b = route_key(origin), route_key(dest)
        return self.routes.get((a, b) if a <= b else (b, a), set())

    def common(self, pairs: Sequence[tuple[str, str]]) -> set[str] | None:
        """Airlines known on EVERY pair; ``None`` when some pair has no data at all (unknown, not "none")."""

        sets = [self.serving(o, d) for o, d in pairs]
        if any(not x for x in sets):
            return None
        return set.intersection(*sets)

    def bonus(self, key: str) -> float:
        """NETWORK_BONUS when one airline flies all legs of ``key``, 0 otherwise (unknown or no common airline)."""

        common = self.common([(o, d) for o, d, _ in parse_key(key)[1]])
        return NETWORK_BONUS if common else 0.0
