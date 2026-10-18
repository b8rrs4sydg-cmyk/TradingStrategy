"""RedisCachingProvider — uses an in-memory fake, no real Redis."""

from __future__ import annotations

from datetime import date

from app.providers.redis_cache import DEFAULT_TTL_SECONDS, RedisCachingProvider
from tests.fake_fares import FakeFareProvider


class _FakeRedis:
    """Minimal interface: ``get`` and ``setex`` with TTL tracked."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}
        self.get_calls = 0
        self.setex_calls = 0

    def get(self, key: str):
        self.get_calls += 1
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: bytes) -> None:
        self.setex_calls += 1
        self.store[key] = value
        self.ttls[key] = ttl


def test_cache_miss_then_hit_round_trips_offers():
    fake = _FakeRedis()
    provider = RedisCachingProvider(FakeFareProvider(), client=fake)

    first = provider.search(
        origin="TPE", destination="NRT",
        departure_date=date(2027, 2, 5), return_date=date(2027, 2, 11),
    )
    assert first
    assert fake.setex_calls == 1
    assert fake.ttls and next(iter(fake.ttls.values())) == DEFAULT_TTL_SECONDS

    second = provider.search(
        origin="TPE", destination="NRT",
        departure_date=date(2027, 2, 5), return_date=date(2027, 2, 11),
    )
    assert second
    assert fake.setex_calls == 1  # still 1 — hit on second call
    assert second[0].total_price == first[0].total_price
    assert second[0].legs[0].origin == first[0].legs[0].origin
    assert provider.stats() == {"hits": 1, "misses": 1}


def test_degrades_gracefully_when_client_is_none():
    provider = RedisCachingProvider(FakeFareProvider(), client=None)
    offers = provider.search(
        origin="TPE", destination="NRT",
        departure_date=date(2027, 2, 5), return_date=date(2027, 2, 11),
    )
    assert offers
    # No cache, so no hits ever
    assert provider.stats() == {"hits": 0, "misses": 1}


def test_degrades_gracefully_when_client_raises():
    class _BrokenRedis:
        def get(self, key: str):
            raise RuntimeError("backend unavailable")

        def setex(self, key: str, ttl: int, value: bytes):
            raise RuntimeError("backend unavailable")

    provider = RedisCachingProvider(FakeFareProvider(), client=_BrokenRedis())
    offers = provider.search(
        origin="TPE", destination="NRT", departure_date=date(2027, 2, 5),
    )
    assert offers  # upstream result still delivered
