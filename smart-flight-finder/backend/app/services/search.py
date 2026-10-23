"""Top-level search orchestrator.

Takes an :class:`ItineraryRequestIn`, runs every requested strategy against the
plug-in provider, merges plans, and ranks via :mod:`app.services.scoring`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from app.data.taiwan_holidays_2027 import LEAVE_STRATEGIES
from app.models.enums import DateWindowRole, TicketStrategyType, TripType
from app.providers.base import FlightOfferProvider
from app.providers.cache import CachingProvider
from app.schemas.itinerary import CandidateWindowIn, DateWindowIn, ItineraryRequestIn
from app.services.date_matrix import expand_window, matrix_cardinality
from app.services.diversity import diversify
from app.services.scoring import score_plans
from app.services.strategies import (
    FourLegPlanner,
    OpenJawPlanner,
    ReverseTicketPlanner,
    StandardPlanner,
    StrategyPlan,
)
from app.services.strategies.reverse import daomai_country
from app.services.strategies.two_trip import TripSlot

logger = logging.getLogger(__name__)


DEFAULT_FARE_DB = Path(__file__).resolve().parents[3] / "public" / "fares.json"


class NoFareSource:
    """No price source configured: every query answers with no offer."""

    name = "none"

    def search(self, **_kw) -> list:
        return []

    def search_multi_city(self, **_kw) -> list:
        return []


def resolve_default_provider() -> FlightOfferProvider:
    """Pick the fare source from env — real prices only, never simulated.

    1. The Google Flights fare database: ``FARE_DB_PATH`` (or the legacy
       ``FARE_SNAPSHOT_PATH``), else the crawler's ``public/fares.json`` in
       this repo. ``LIVE_FARES=1`` adds live Google Flights lookups for
       queries the database lacks (``LIVE_FARE_BUDGET`` per request, default
       24; needs Playwright + Chromium) and saves them back.
    2. Amadeus Enterprise / Skyscanner credentials, if set (Amadeus
       Self-Service shut down 2026-07-17).
    3. Otherwise :class:`NoFareSource` — searches return no plans and a notice.

    When ``REDIS_URL`` is set, the provider is wrapped in a
    :class:`RedisCachingProvider` shared across requests.
    """

    base: FlightOfferProvider = NoFareSource()
    db_path = os.getenv("FARE_DB_PATH") or os.getenv("FARE_SNAPSHOT_PATH")
    if db_path or DEFAULT_FARE_DB.exists():
        try:
            from app.providers.fare_db import FareDatabaseProvider

            live = os.getenv("LIVE_FARES") == "1"
            fetcher = None
            if live:
                from app.providers.google_flights import fetch_now

                fetcher = fetch_now
            path = Path(db_path) if db_path else DEFAULT_FARE_DB
            if path.exists() or live:
                base = FareDatabaseProvider.from_path(
                    path,
                    fetcher=fetcher,
                    live_budget=int(os.getenv("LIVE_FARE_BUDGET", "24")) if live else 0,
                )
        except (OSError, ValueError) as e:
            logger.warning("fare_db_load_failed", extra={"err": str(e)})
    if isinstance(base, NoFareSource):
        if os.getenv("AMADEUS_CLIENT_ID") and os.getenv("AMADEUS_CLIENT_SECRET"):
            try:
                from app.providers.amadeus import AmadeusError, AmadeusProvider

                base = AmadeusProvider(env=os.getenv("AMADEUS_ENV", "test"))
            except AmadeusError as e:
                logger.warning("amadeus_init_failed", extra={"err": str(e)})
        elif os.getenv("SKYSCANNER_RAPIDAPI_KEY"):
            try:
                from app.providers.skyscanner import SkyscannerError, SkyscannerProvider

                base = SkyscannerProvider()
            except SkyscannerError as e:
                logger.warning("skyscanner_init_failed", extra={"err": str(e)})

    if os.getenv("REDIS_URL"):
        try:
            from app.providers.redis_cache import RedisCachingProvider

            return RedisCachingProvider(base)
        except Exception as e:  # pragma: no cover  # noqa: BLE001 — any Redis failure degrades gracefully
            logger.warning("redis_cache_init_failed", extra={"err": str(e)})
    return base


NO_FARE_SOURCE = "尚未設定票價資料庫：請先執行票價爬蟲（Fare snapshot workflow）或設定 FARE_DB_PATH。"
UNCOVERED = (
    "{n} 個票價查詢不在 Google Flights 票價資料庫內（爬蟲尚未涵蓋這些機場/日期），"
    "相關方案已略過；資料庫更新於 {at}。"
)


# Strategies whose whole point is covering TWO trips with interleaved tickets.

NEED_TWO_SLOTS = (
    "反向票＋倒買法是「一次購票、兩趟旅程」的買法，"
    "需要至少兩個不重疊的備選時段（例如 春節 + 聖誕）且行程類型為來回。"
)
NEED_THREE_SLOTS = (
    "外站四腿票串起三趟旅程（單買初段＋第1段 / 第2+3段 / 第4段＋單買最後一段），"
    "需要至少三個不重疊的備選時段（例如 春節 + 清明 + 端午）且行程類型為來回。"
)

DAOMAI_ASIA_ONLY = (
    "倒買法只適用日本、泰國（偶爾韓國）等亞洲短程 — 這些國家出發的來回票才便宜且常見；"
    "{} 不套用反向票＋倒買法。"
)


class SearchService:
    def __init__(self, provider: FlightOfferProvider | None = None) -> None:
        self._raw_provider = provider or resolve_default_provider()
        self.provider: CachingProvider | FlightOfferProvider = self._raw_provider
        self.notices: list[str] = []

    def run(
        self, req: ItineraryRequestIn
    ) -> tuple[int, list[StrategyPlan], dict[str, int]]:
        """Return (date_matrix_size, ranked plans, provider cache stats).

        With ``req.candidate_windows`` every strategy runs once per 備選時段;
        each plan is tagged with its slot's label, and plans that overlapping
        slots both produced (same strategy + same tickets) are kept once.
        """

        raw = self._raw_provider
        if hasattr(raw, "prefetch"):
            # Dry run to learn every query, then fetch missing ones live (if on).
            from app.services.query_plan import required_queries

            def dry_run(rec) -> None:
                self.provider = rec
                self._collect(req)

            raw.prefetch(required_queries(dry_run))

        # Fresh cache per request — never leak offers between users.
        self.provider = CachingProvider(raw)
        total_matrix, plans = self._collect(req)

        if req.max_total_budget is not None:
            plans = [p for p in plans if p.total_cost <= req.max_total_budget]

        if isinstance(raw, NoFareSource):
            self.notices.insert(0, NO_FARE_SOURCE)
        elif getattr(raw, "misses", 0):
            at = (getattr(getattr(raw, "db", None), "generated_at", None) or "—")[:16].replace("T", " ")
            self.notices.append(UNCOVERED.format(n=raw.misses, at=at))

        ranked = diversify(score_plans(plans, weights=req.scoring_weights))
        stats = self.provider.stats() if isinstance(self.provider, CachingProvider) else {}
        return total_matrix, ranked, stats

    def _collect(self, req: ItineraryRequestIn) -> tuple[int, list[StrategyPlan]]:
        self.notices = []
        slots: list[tuple[str | None, list[DateWindowIn]]]
        if req.candidate_windows:
            slots = [
                (_slot_label(c), _windows_from_candidate(c, req.trip_type))
                for c in req.candidate_windows
            ]
        else:
            slots = [(None, req.date_windows)]

        plans: list[StrategyPlan] = []
        seen: set[tuple[TicketStrategyType, tuple[str, ...]]] = set()

        def add(plan: StrategyPlan, label: str | None) -> None:
            key = (plan.strategy, tuple(t.offer_id for t in plan.tickets))
            if key in seen:
                return
            seen.add(key)
            plans.append(replace(plan, window_label=label) if label else plan)

        wanted = [s for s in req.strategies if s in RUNNERS]
        # one loop for every strategy: each declares how many trips (slots) it spans and gets those subjects
        by_arity: dict[int, list[TicketStrategyType]] = {}
        for strategy in wanted:
            if strategy is TicketStrategyType.BACK_TO_BACK_4LEG and not req.back_to_back_outer_stations:
                continue
            by_arity.setdefault(RUNNERS[strategy].arity, []).append(strategy)

        total_matrix = 0
        for label, windows in slots:
            expanded = [expand_window(w) for w in windows]
            total_matrix += matrix_cardinality(expanded)
            for strategy in by_arity.get(1, []):
                for plan in RUNNERS[strategy].run(self.provider, req, expanded):
                    add(plan, label)

        for arity, empty_notice in ((2, NEED_TWO_SLOTS), (3, NEED_THREE_SLOTS)):
            strategies = by_arity.get(arity, [])
            if not strategies:
                continue
            chains = _slot_pairs(req) if arity == 2 else _slot_triples(req)
            if not chains:
                self.notices.append(empty_notice)
            if TicketStrategyType.REVERSE in strategies:
                skipped = [d for d in req.destinations if daomai_country(d) is None]
                if skipped:
                    self.notices.append(DAOMAI_ASIA_ONLY.format(", ".join(skipped)))
            for chain in chains:
                for strategy in strategies:
                    for plan in RUNNERS[strategy].run(self.provider, req, chain):
                        add(plan, " + ".join(t.label for t in chain))
        return total_matrix, plans


@dataclass(frozen=True)
class StrategyRunner:
    """How the orchestrator drives one strategy: how many trips it spans and how to run its planner on them."""

    arity: int  # 1 = date windows of one trip, 2 = ordered pair of slots, 3 = ordered triple of slots
    run: Callable[[FlightOfferProvider, ItineraryRequestIn, object], list[StrategyPlan]]


RUNNERS: dict[TicketStrategyType, StrategyRunner] = {
    TicketStrategyType.STANDARD: StrategyRunner(
        1,
        lambda prov, req, expanded: StandardPlanner(prov).plan(
            expanded=expanded,
            origins=req.origins,
            destinations=req.destinations,
            trip_type=req.trip_type,
            adults=req.adults,
        ),
    ),
    TicketStrategyType.OPEN_JAW: StrategyRunner(
        1,
        lambda prov, req, expanded: OpenJawPlanner(prov).plan(
            expanded=expanded, origins=req.origins, destinations=req.destinations, adults=req.adults
        ),
    ),
    TicketStrategyType.REVERSE: StrategyRunner(
        2,
        lambda prov, req, ab: ReverseTicketPlanner(prov).plan(
            trip_a=ab[0], trip_b=ab[1], origins=req.origins, destinations=req.destinations, adults=req.adults
        ),
    ),
    TicketStrategyType.BACK_TO_BACK_4LEG: StrategyRunner(
        3,
        lambda prov, req, pqr: FourLegPlanner(prov).plan(
            trip_p=pqr[0],
            trip_q=pqr[1],
            trip_r=pqr[2],
            outer_stations=req.back_to_back_outer_stations,
            destinations=req.destinations,
            adults=req.adults,
        ),
    ),
}
# Hidden-city planner intentionally left out — needs careful fare-rule review before shipping.


def _slots(req: ItineraryRequestIn) -> list[TripSlot]:
    """Round-trip candidate windows as trip slots (empty unless round trip)."""

    if req.trip_type is not TripType.ROUND_TRIP:
        return []
    slots = [
        TripSlot(
            label=_slot_label(c),
            departs=expand_window(ws[0]).candidates,
            returns=expand_window(ws[1]).candidates,
        )
        for c in req.candidate_windows
        if len(ws := _windows_from_candidate(c, req.trip_type)) == 2
    ]
    return slots


def _slot_pairs(req: ItineraryRequestIn) -> list[tuple[TripSlot, TripSlot]]:
    """Ordered (earlier, later) pairs of round-trip slots that don't overlap."""

    slots = _slots(req)
    return [(a, b) for a in slots for b in slots if a is not b and max(a.returns) < min(b.departs)]


def _slot_triples(req: ItineraryRequestIn) -> list[tuple[TripSlot, TripSlot, TripSlot]]:
    """Ordered non-overlapping slot chains (P before Q before R)."""

    slots = _slots(req)
    return [
        (a, b, c)
        for a in slots
        for b in slots
        for c in slots
        if len({id(a), id(b), id(c)}) == 3
        and max(a.returns) < min(b.departs)
        and max(b.returns) < min(c.departs)
    ]


def _slot_label(c: CandidateWindowIn) -> str:
    if c.label:
        return c.label
    match = next((s for s in LEAVE_STRATEGIES if s.holiday_key == c.holiday_key), None)
    if match is not None:
        return match.label_zh
    if c.return_date is None:
        return c.depart.isoformat()
    return f"{c.depart:%m/%d}–{c.return_date:%m/%d}"


def _windows_from_candidate(c: CandidateWindowIn, trip_type: TripType) -> list[DateWindowIn]:
    windows = [
        DateWindowIn(
            role=DateWindowRole.OUTBOUND,
            anchor_date=c.depart,
            flex_before=c.depart_flex,
            flex_after=c.depart_flex,
        )
    ]
    if trip_type is TripType.ROUND_TRIP and c.return_date is not None:
        windows.append(
            DateWindowIn(
                role=DateWindowRole.RETURN,
                anchor_date=c.return_date,
                flex_before=c.return_flex,
                flex_after=c.return_flex,
            )
        )
    return windows
