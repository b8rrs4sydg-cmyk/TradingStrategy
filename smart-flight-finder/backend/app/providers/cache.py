"""Request-scoped provider cache.

The strategy engines (especially :class:`FourLegPlanner`) repeatedly ask the
same provider for the same (OD, dates) tuple. Wrapping the real provider in
``CachingProvider`` memoizes those lookups for the lifetime of one search —
after Phase 5 this is the single largest perf win on the stub, and the same
hook will later feed a Redis-backed cache in production.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from app.providers.base import FlightOfferProvider

if TYPE_CHECKING:
    from app.services.strategies.base import TicketOffer


class CachingProvider:
    """Thin wrapper that deduplicates ``search`` calls for one request."""

    def __init__(self, inner: FlightOfferProvider) -> None:
        self._inner = inner
        self._cache: dict[tuple, list[TicketOffer]] = {}
        self._hits = 0
        self._misses = 0

    @property
    def name(self) -> str:
        return f"cached:{self._inner.name}"

    def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 1,
    ) -> list[TicketOffer]:
        key = (origin, destination, departure_date, return_date, adults)
        if key in self._cache:
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        offers = self._inner.search(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        )
        self._cache[key] = offers
        return offers

    def stats(self) -> dict[str, int]:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "unique_queries": len(self._cache),
        }
