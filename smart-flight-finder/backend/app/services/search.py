"""Top-level search orchestrator.

Takes an :class:`ItineraryRequestIn`, runs every requested strategy against the
plug-in provider, merges plans, and ranks via :mod:`app.services.scoring`.
"""

from __future__ import annotations

import logging
import os

from app.models.enums import TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.providers.cache import CachingProvider
from app.providers.stub import StubFlightProvider
from app.schemas.itinerary import ItineraryRequestIn
from app.services.date_matrix import expand_itinerary, matrix_cardinality
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
            logger.warning("amadeus_init_failed_falling_back_to_stub", extra={"err": str(e)})

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
        """Return (date_matrix_size, ranked plans, provider cache stats)."""

        # Fresh cache per request — never leak offers between users.
        self.provider = CachingProvider(self._raw_provider)

        expanded = expand_itinerary(req)
        matrix_size = matrix_cardinality(expanded)

        plans: list[StrategyPlan] = []
        for strategy in req.strategies:
            plans.extend(self._run_strategy(strategy, req, expanded))

        if req.max_total_budget is not None:
            plans = [p for p in plans if p.total_cost <= req.max_total_budget]

        ranked = score_plans(plans, weights=req.scoring_weights)
        stats = self.provider.stats() if isinstance(self.provider, CachingProvider) else {}
        return matrix_size, ranked, stats

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
