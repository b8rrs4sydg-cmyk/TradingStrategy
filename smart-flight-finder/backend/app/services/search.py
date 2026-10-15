"""Top-level search orchestrator.

Takes an :class:`ItineraryRequestIn`, runs every requested strategy against the
plug-in provider, merges plans, and ranks via :mod:`app.services.scoring`.
"""

from __future__ import annotations

from app.models.enums import TicketStrategyType
from app.providers.base import FlightOfferProvider
from app.providers.stub import StubFlightProvider
from app.schemas.itinerary import ItineraryRequestIn
from app.services.date_matrix import expand_itinerary, matrix_cardinality
from app.services.scoring import score_plans
from app.services.strategies import (
    FourLegPlanner,
    ReverseTicketPlanner,
    StandardPlanner,
    StrategyPlan,
)


class SearchService:
    def __init__(self, provider: FlightOfferProvider | None = None) -> None:
        self.provider = provider or StubFlightProvider()

    def run(self, req: ItineraryRequestIn) -> tuple[int, list[StrategyPlan]]:
        """Return (date_matrix_size, ranked plans)."""

        expanded = expand_itinerary(req)
        matrix_size = matrix_cardinality(expanded)

        plans: list[StrategyPlan] = []
        for strategy in req.strategies:
            plans.extend(self._run_strategy(strategy, req, expanded))

        if req.max_total_budget is not None:
            plans = [p for p in plans if p.total_cost <= req.max_total_budget]

        ranked = score_plans(plans, weights=req.scoring_weights)
        return matrix_size, ranked

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
        # Open-jaw & hidden-city planners not yet implemented in Phase 1 scaffold
        return []
