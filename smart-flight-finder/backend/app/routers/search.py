"""POST /search — orchestration endpoint for Phase 2+3 engines."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.metrics import inc_counter
from app.core.rate_limit import enforce_rate_limit
from app.schemas import ItineraryRequestIn, SearchResult, StrategyPlanOut
from app.services.search import SearchService

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=SearchResult,
    dependencies=[Depends(enforce_rate_limit)],
)
def search(req: ItineraryRequestIn) -> SearchResult:
    service = SearchService()
    matrix_size, plans, cache_stats = service.run(req)

    provider_name = getattr(service._raw_provider, "name", "unknown")
    inc_counter("sff_search_requests_total", labels={"provider": provider_name})
    inc_counter("sff_search_plans_total", by=len(plans), labels={"provider": provider_name})
    if cache_stats:
        inc_counter("sff_provider_cache_hits_total", by=float(cache_stats.get("hits", 0)))
        inc_counter("sff_provider_cache_misses_total", by=float(cache_stats.get("misses", 0)))
    for strategy in req.strategies:
        inc_counter("sff_strategy_requested_total", labels={"strategy": strategy.value})

    return SearchResult(
        request_echo=req.model_dump(mode="json"),
        date_matrix_size=matrix_size,
        plans=[StrategyPlanOut.of(p, adults=req.adults, cabin=req.cabin) for p in plans],
        provider_cache=cache_stats,
    )
