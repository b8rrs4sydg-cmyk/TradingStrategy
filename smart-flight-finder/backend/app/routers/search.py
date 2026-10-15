"""POST /search — orchestration endpoint for Phase 2+3 engines."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import ItineraryRequestIn, SearchResult, StrategyPlanOut
from app.services.search import SearchService

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResult)
def search(req: ItineraryRequestIn) -> SearchResult:
    service = SearchService()
    matrix_size, plans = service.run(req)
    return SearchResult(
        request_echo=req.model_dump(mode="json"),
        date_matrix_size=matrix_size,
        plans=[StrategyPlanOut.of(p) for p in plans],
    )
