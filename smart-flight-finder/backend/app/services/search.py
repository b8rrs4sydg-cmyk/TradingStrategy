"""Top-level search orchestrator.

Takes an :class:`ItineraryRequestIn`, runs every requested strategy against the
plug-in provider, merges plans, and ranks via :mod:`app.services.scoring`.
"""

from __future__ import annotations

import logging
import os

from app.data.taiwan_holidays_2027 import LEAVE_STRATEGIES
from app.models.enums import DateWindowRole, TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.providers.cache import CachingProvider
from app.providers.stub import StubFlightProvider
from app.schemas.itinerary import DateWindowIn, ItineraryRequestIn
from app.services.date_matrix import expand_window, matrix_cardinality
from app.services.scoring import score_plans
from app.services.strategies import (
    FourLegPlanner,
    OpenJawPlanner,
    ReverseTicketPlanner,
    StandardPlanner,
    StrategyPlan,
)

logger = logging.getLogger(__name__)


def resolve_default_provider() -> FlightOfferProvider:
    """Pick a provider from env: Amadeus if both credentials are set, else Stub.

    When ``REDIS_URL`` is set, wrap the chosen provider in a
    :class:`RedisCachingProvider` so repeated searches across users share a
    TTL cache (default 2h). ``CachingProvider`` is still added per-request
    on top by :class:`SearchService` to collapse intra-request fan-out.

    Imports are lazy so unit tests that don't need Amadeus or Redis skip
    the extra imports entirely.
    """

    base: FlightOfferProvider = StubFlightProvider()
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


class SearchService:
    def __init__(self, provider: FlightOfferProvider | None = None) -> None:
        self._raw_provider = provider or resolve_default_provider()
        self.provider: CachingProvider | FlightOfferProvider = self._raw_provider

    def run(
        self, req: ItineraryRequestIn
    ) -> tuple[int, list[StrategyPlan], dict[str, int]]:
        """Return (date_matrix_size, ranked plans, provider cache stats).

        When ``req.holiday_keys`` is set, each key is treated as an independent
        candidate (outbound, return) window and every strategy is run against
        each in turn, with results merged — this is how multi-holiday search
        permutes 春節 / 聖誕 / 元旦 / … to find the best 4-leg across the year.
        """

        # Fresh cache per request — never leak offers between users.
        self.provider = CachingProvider(self._raw_provider)

        plans: list[StrategyPlan] = []
        total_matrix = 0

        candidate_windows_sets: list[list[DateWindowIn]]
        if req.holiday_keys:
            candidate_windows_sets = [
                _windows_from_holiday(key, flex=req.holiday_flex_days)
                for key in req.holiday_keys
            ]
            # Drop keys that don't resolve to a known holiday.
            candidate_windows_sets = [w for w in candidate_windows_sets if w]
        else:
            candidate_windows_sets = [req.date_windows]

        for windows in candidate_windows_sets:
            expanded = [expand_window(w) for w in windows]
            total_matrix += matrix_cardinality(expanded)
            for strategy in req.strategies:
                plans.extend(self._run_strategy(strategy, req, expanded))

        if req.max_total_budget is not None:
            plans = [p for p in plans if p.total_cost <= req.max_total_budget]

        ranked = score_plans(plans, weights=req.scoring_weights)
        stats = self.provider.stats() if isinstance(self.provider, CachingProvider) else {}
        return total_matrix, ranked, stats

    # ------------------------------------------------------------------
    def _run_strategy(
        self,
        strategy: TicketStrategyType,
        req: ItineraryRequestIn,
        expanded,
    ) -> list[StrategyPlan]:
        if strategy is TicketStrategyType.STANDARD:
            return StandardPlanner(self.provider).plan(
                expanded=expanded,
                origins=req.origins,
                destinations=req.destinations,
                trip_type=req.trip_type,
                adults=req.adults,
            )
        if strategy is TicketStrategyType.REVERSE:
            return ReverseTicketPlanner(self.provider).plan(
                expanded=expanded,
                origins=req.origins,
                destinations=req.destinations,
                adults=req.adults,
            )
        if strategy is TicketStrategyType.BACK_TO_BACK_4LEG:
            outer = req.back_to_back_outer_stations
            if not outer:
                return []
            return FourLegPlanner(self.provider).plan(
                expanded=expanded,
                outer_stations=outer,
                destinations=req.destinations,
                outer_buffer_days=req.back_to_back_outer_buffer_days,
                adults=req.adults,
            )
        if strategy is TicketStrategyType.OPEN_JAW:
            return OpenJawPlanner(self.provider).plan(
                expanded=expanded,
                origins=req.origins,
                destinations=req.destinations,
                adults=req.adults,
            )
        # Hidden-city planner intentionally left out — needs careful fare-rule
        # review before shipping, and the UX implications are non-trivial.
        return []


def _windows_from_holiday(holiday_key: str, *, flex: int) -> list[DateWindowIn]:
    """Resolve a 2027 TW leave-strategy key into (outbound, return) windows.

    Each selected holiday becomes one candidate (outbound, return) pair; the
    orchestrator loops the full strategy roster across all pairs so the user
    can let the engine pick 春節 vs 聖誕 vs 元旦 (etc.) by cost + score.
    """

    match = next((s for s in LEAVE_STRATEGIES if s.holiday_key == holiday_key), None)
    if match is None:
        return []
    return [
        DateWindowIn(
            role=DateWindowRole.OUTBOUND,
            anchor_date=match.window_start,
            flex_before=flex,
            flex_after=flex,
        ),
        DateWindowIn(
            role=DateWindowRole.RETURN,
            anchor_date=match.window_end,
            flex_before=flex,
            flex_after=flex,
        ),
    ]
