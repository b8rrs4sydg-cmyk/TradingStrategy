from datetime import date

from app.providers.base import FlightOfferProvider
from app.providers.cache import CachingProvider
from app.providers.stub import StubFlightProvider
from app.services.strategies.base import TicketOffer


class _CountingStub:
    name = "counting-stub"

    def __init__(self, inner: FlightOfferProvider) -> None:
        self.inner = inner
        self.calls = 0

    def search(self, **kw) -> list[TicketOffer]:
        self.calls += 1
        return self.inner.search(**kw)


def test_cache_deduplicates_identical_calls():
    inner = _CountingStub(StubFlightProvider())
    cached = CachingProvider(inner)

    for _ in range(5):
        cached.search(
            origin="TPE",
            destination="NRT",
            departure_date=date(2027, 2, 5),
            return_date=date(2027, 2, 11),
            adults=1,
        )
    assert inner.calls == 1
    stats = cached.stats()
    assert stats == {"hits": 4, "misses": 1, "total": 5, "unique_queries": 1}


def test_cache_separate_adults_key():
    inner = _CountingStub(StubFlightProvider())
    cached = CachingProvider(inner)
    cached.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 5), adults=1)
    cached.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 5), adults=2)
    assert inner.calls == 2
