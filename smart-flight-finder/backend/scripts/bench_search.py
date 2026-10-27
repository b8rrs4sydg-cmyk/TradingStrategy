"""Benchmark the search service against the configured fare source (the fare DB).

Measures:
- Wall-clock time per strategy
- Provider cache hit/miss ratio
- Date-matrix cardinality

Usage::

    python -m scripts.bench_search --flex 3 --outer-buffer 3
"""

from __future__ import annotations

import argparse
import time
from datetime import date

from app.models.enums import (
    CabinClass,
    TicketStrategyType,
    TripType,
)
from app.schemas.itinerary import CandidateWindowIn, ItineraryRequestIn
from app.services.search import SearchService


def build_request(flex: int) -> ItineraryRequestIn:
    def slot(key: str, dep: date, ret: date) -> CandidateWindowIn:
        return CandidateWindowIn(
            holiday_key=key, depart=dep, return_date=ret, depart_flex=flex, return_flex=flex
        )

    return ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP,
        cabin=CabinClass.ECONOMY,
        adults=1,
        origins=["TPE"],
        destinations=["NRT", "HND", "KIX", "ICN", "BKK"],
        strategies=[
            TicketStrategyType.STANDARD,
            TicketStrategyType.REVERSE,
            TicketStrategyType.BACK_TO_BACK_4LEG,
        ],
        back_to_back_outer_stations=["XMN", "HKG"],
        candidate_windows=[
            slot("lunar_ny", date(2027, 2, 5), date(2027, 2, 15)),
            slot("xmas", date(2027, 12, 23), date(2027, 12, 27)),
        ],
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--flex", type=int, default=3, help="±N days per window")
    args = p.parse_args()

    req = build_request(args.flex)
    service = SearchService()
    t0 = time.perf_counter()
    matrix_size, plans, stats = service.run(req)
    elapsed = time.perf_counter() - t0

    print(f"Request:   flex=±{args.flex}")
    print(f"Matrix:    {matrix_size} candidate date combinations (pre-prune)")
    print(f"Plans:     {len(plans)}")
    print(
        f"Provider:  {stats.get('misses', 0):4d} unique queries · "
        f"{stats.get('hits', 0):4d} cache hits · "
        f"{stats.get('total', 0):4d} total calls"
    )
    if stats.get("total", 0):
        hit_rate = stats.get("hits", 0) / stats["total"]
        print(f"Hit rate:  {hit_rate:.1%}")
    print(f"Elapsed:   {elapsed * 1000:.1f} ms")

    if plans:
        best = plans[0]
        print(
            f"\nTop plan:  {best.strategy.value}  "
            f"{best.total_cost:,} {best.currency}  "
            f"score={best.score}"
        )
        if best.explain:
            print(f"           {best.explain}")


if __name__ == "__main__":
    main()
