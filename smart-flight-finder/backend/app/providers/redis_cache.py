"""Redis-backed cross-request offer cache.

Why two layers?

- :class:`CachingProvider` (request-scoped) kills intra-request fan-out
  (89% hit rate on the stub benchmark).
- :class:`RedisCachingProvider` persists results across users and across
  pod restarts with a TTL — critical in production because real APIs like
  Amadeus charge per call and have strict rate limits.

Keys are stable across versions so a rolling deploy keeps the cache warm.
Values are JSON-serialized TicketOffer tuples; FlightLeg datetimes become
ISO strings. If Redis is down the provider degrades gracefully and the
upstream call still runs.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from app.providers.base import FlightOfferProvider

if TYPE_CHECKING:
    import redis

    from app.services.strategies.base import TicketOffer

logger = logging.getLogger(__name__)

_KEY_PREFIX = "sff:offers:v1"
DEFAULT_TTL_SECONDS = 60 * 60 * 2  # 2h


class RedisCachingProvider:
    """Durable cache in front of a real :class:`FlightOfferProvider`.

    Not safe to share between threads without the standard redis-py client,
    which is thread-safe for GET/SETEX.
    """

    def __init__(
        self,
        inner: FlightOfferProvider,
        *,
        client: redis.Redis | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        url: str | None = None,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._client = client or _connect(url or os.getenv("REDIS_URL"))
        self._hits = 0
        self._misses = 0

    @property
    def name(self) -> str:
        inner_name = getattr(self._inner, "name", "unknown")
        return f"redis:{inner_name}"

    def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 1,
    ) -> list[TicketOffer]:
        key = _key(origin, destination, departure_date, return_date, adults)
        cached = self._safe_get(key)
        if cached is not None:
            self._hits += 1
            return _decode_offers(cached)

        self._misses += 1
        offers = self._inner.search(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        )
        self._safe_set(key, _encode_offers(offers))
        return offers

    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses}

    # ------------------------------------------------------------------
    def _safe_get(self, key: str) -> bytes | None:
        if self._client is None:
            return None
        try:
            return self._client.get(key)
        except Exception:  # pragma: no cover — redis-py error families vary
            logger.warning("redis_get_failed", extra={"key": key}, exc_info=True)
            return None

    def _safe_set(self, key: str, value: bytes) -> None:
        if self._client is None:
            return
        try:
            self._client.setex(key, self._ttl, value)
        except Exception:  # pragma: no cover
            logger.warning("redis_setex_failed", extra={"key": key}, exc_info=True)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _key(
    origin: str,
    destination: str,
    departure_date: date,
    return_date: date | None,
    adults: int,
) -> str:
    ret = return_date.isoformat() if return_date else "-"
    return f"{_KEY_PREFIX}:{origin}:{destination}:{departure_date.isoformat()}:{ret}:{adults}"


def _encode_offers(offers: list[TicketOffer]) -> bytes:
    return json.dumps([_dc_to_json(o) for o in offers], default=_json_default).encode("utf-8")


def _decode_offers(raw: bytes) -> list[TicketOffer]:
    from app.models.enums import CabinClass
    from app.services.strategies.base import FlightLeg, TicketOffer

    data = json.loads(raw)
    offers: list[TicketOffer] = []
    for o in data:
        legs = tuple(
            FlightLeg(
                origin=L["origin"],
                destination=L["destination"],
                departure=datetime.fromisoformat(L["departure"]),
                arrival=datetime.fromisoformat(L["arrival"]),
                carrier=L["carrier"],
                flight_number=L["flight_number"],
                cabin=CabinClass(L.get("cabin", "economy")),
                stops=L.get("stops", 0),
            )
            for L in o["legs"]
        )
        offers.append(
            TicketOffer(
                offer_id=o["offer_id"],
                legs=legs,
                total_price=o["total_price"],
                currency=o["currency"],
                fare_class=o.get("fare_class"),
                baggage_through_checked=o.get("baggage_through_checked", True),
                issuer=o.get("issuer"),
            )
        )
    return offers


def _dc_to_json(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"not serializable: {type(obj)!r}")


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"not JSON-serializable: {type(value)!r}")


def _connect(url: str | None):
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0)
    except Exception:  # pragma: no cover — missing extra at dev time
        logger.warning("redis_import_or_connect_failed", exc_info=True)
        return None
