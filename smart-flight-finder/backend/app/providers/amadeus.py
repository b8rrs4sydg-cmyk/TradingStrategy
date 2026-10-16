"""Amadeus Self-Service Flight Offers Search adapter.

Docs:
- OAuth2:  https://developers.amadeus.com/self-service/apis-docs/guides/authorization-262
- Search:  https://developers.amadeus.com/self-service/category/flights/api-doc/flight-offers-search

Env vars (populated from ``.env`` → ``app.config.Settings``):

    AMADEUS_CLIENT_ID       (API key)
    AMADEUS_CLIENT_SECRET   (API secret)
    AMADEUS_ENV             "test" (default) | "production"

Only one offer per direction/date is returned (:func:`search`) to match the
``FlightOfferProvider`` protocol; callers memoize via :class:`CachingProvider`.

The adapter is intentionally thin — it maps the Amadeus payload into
``TicketOffer``/``FlightLeg`` and lets the strategy engines decide what to do.
Error handling raises :class:`AmadeusError`; the search service should catch
and fall back to the stub provider if desired.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar

import httpx

from app.models.enums import CabinClass
from app.providers.base import FlightOfferProvider
from app.services.strategies.base import FlightLeg, TicketOffer

logger = logging.getLogger(__name__)


class AmadeusError(RuntimeError):
    pass


@dataclass(slots=True)
class _Token:
    access_token: str
    expires_at: float   # unix seconds


class AmadeusProvider:
    """Flight-offer provider talking to Amadeus Self-Service."""

    name: ClassVar[str] = "amadeus"

    _BASES: ClassVar[dict[str, str]] = {
        "test": "https://test.api.amadeus.com",
        "production": "https://api.amadeus.com",
    }

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        env: str = "test",
        timeout_s: float = 15.0,
    ) -> None:
        self.client_id = client_id or os.getenv("AMADEUS_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("AMADEUS_CLIENT_SECRET", "")
        if not self.client_id or not self.client_secret:
            raise AmadeusError(
                "AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET not configured"
            )
        if env not in self._BASES:
            raise AmadeusError(f"Unknown Amadeus env: {env}")
        self.base = self._BASES[env]
        self.timeout = timeout_s
        self._token: _Token | None = None

    # ------------------------------------------------------------------
    def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 1,
    ) -> list[TicketOffer]:
        params: dict[str, object] = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date.isoformat(),
            "adults": adults,
            "max": 10,
            "currencyCode": "TWD",
            "nonStop": "false",
        }
        if return_date is not None:
            params["returnDate"] = return_date.isoformat()

        token = self._bearer()
        url = f"{self.base}/v2/shopping/flight-offers"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code >= 400:
                logger.warning("amadeus_search_failed", extra={
                    "status": resp.status_code, "params": params,
                })
                raise AmadeusError(f"Amadeus search failed: {resp.status_code} {resp.text[:200]}")
            payload = resp.json()

        return [_parse_offer(raw) for raw in payload.get("data", [])]

    # ------------------------------------------------------------------
    def _bearer(self) -> str:
        now = time.time()
        if self._token and self._token.expires_at - 30 > now:
            return self._token.access_token

        url = f"{self.base}/v1/security/oauth2/token"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code != 200:
                raise AmadeusError(
                    f"OAuth failed: {resp.status_code} {resp.text[:200]}"
                )
            body = resp.json()

        self._token = _Token(
            access_token=body["access_token"],
            expires_at=now + float(body.get("expires_in", 1800)),
        )
        return self._token.access_token


# ---------------------------------------------------------------------------
# Payload parsing
# ---------------------------------------------------------------------------
def _parse_offer(raw: dict) -> TicketOffer:
    legs: list[FlightLeg] = []
    for itin in raw.get("itineraries", []):
        for seg in itin.get("segments", []):
            legs.append(
                FlightLeg(
                    origin=seg["departure"]["iataCode"],
                    destination=seg["arrival"]["iataCode"],
                    departure=datetime.fromisoformat(seg["departure"]["at"]),
                    arrival=datetime.fromisoformat(seg["arrival"]["at"]),
                    carrier=seg.get("carrierCode", "??"),
                    flight_number=f"{seg.get('carrierCode', '??')}{seg.get('number', '')}",
                    cabin=_cabin(raw),
                    stops=max(0, int(seg.get("numberOfStops", 0))),
                )
            )
    price = raw.get("price", {})
    total_price_str = price.get("grandTotal") or price.get("total") or "0"
    return TicketOffer(
        offer_id=str(raw.get("id", "amadeus-unknown")),
        legs=tuple(legs),
        total_price=round(float(total_price_str)),
        currency=price.get("currency", "TWD"),
        fare_class=_fare_class(raw),
        baggage_through_checked=True,
        issuer="amadeus",
    )


def _cabin(raw: dict) -> CabinClass:
    tp = raw.get("travelerPricings") or []
    if not tp:
        return CabinClass.ECONOMY
    seg_details = (tp[0] or {}).get("fareDetailsBySegment") or []
    if not seg_details:
        return CabinClass.ECONOMY
    code = (seg_details[0].get("cabin") or "ECONOMY").upper()
    return {
        "ECONOMY": CabinClass.ECONOMY,
        "PREMIUM_ECONOMY": CabinClass.PREMIUM_ECONOMY,
        "BUSINESS": CabinClass.BUSINESS,
        "FIRST": CabinClass.FIRST,
    }.get(code, CabinClass.ECONOMY)


def _fare_class(raw: dict) -> str | None:
    tp = raw.get("travelerPricings") or []
    if not tp:
        return None
    seg_details = (tp[0] or {}).get("fareDetailsBySegment") or []
    if not seg_details:
        return None
    return seg_details[0].get("class") or None


# sanity: it satisfies the Protocol
_: type[FlightOfferProvider] = AmadeusProvider
