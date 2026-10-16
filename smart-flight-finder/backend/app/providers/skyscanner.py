"""Skyscanner (via RapidAPI) adapter — second data source listed in the spec.

The public Skyscanner API has been shut down for years; the usable endpoints
today are resold on RapidAPI under names like ``skyscanner80`` or
``skyscanner50``. This adapter targets the common shape documented across
those listings (``/api/v1/flights/search-one-way`` and the round-trip variant),
with Pydantic-less manual parsing to stay dependency-light.

Env vars:

    SKYSCANNER_RAPIDAPI_KEY     RapidAPI API key
    SKYSCANNER_RAPIDAPI_HOST    e.g. "skyscanner80.p.rapidapi.com" (overridable
                                 so you can swap resold versions)

Caller behavior mirrors :class:`AmadeusProvider`: raise :class:`SkyscannerError`
on misconfiguration / non-2xx; the search service decides whether to fall back.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any, ClassVar

import httpx

from app.models.enums import CabinClass
from app.providers.base import FlightOfferProvider
from app.services.strategies.base import FlightLeg, TicketOffer

logger = logging.getLogger(__name__)


class SkyscannerError(RuntimeError):
    pass


class SkyscannerProvider:
    name: ClassVar[str] = "skyscanner"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        host: str | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self.api_key = api_key or os.getenv("SKYSCANNER_RAPIDAPI_KEY", "")
        self.host = host or os.getenv("SKYSCANNER_RAPIDAPI_HOST", "skyscanner80.p.rapidapi.com")
        if not self.api_key:
            raise SkyscannerError("SKYSCANNER_RAPIDAPI_KEY not configured")
        self.timeout = timeout_s

    def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 1,
    ) -> list[TicketOffer]:
        path = (
            "/api/v1/flights/search-one-way"
            if return_date is None
            else "/api/v1/flights/search-roundtrip"
        )
        params: dict[str, Any] = {
            "fromId": origin,
            "toId": destination,
            "departDate": departure_date.isoformat(),
            "adults": adults,
            "currency": "TWD",
            "market": "TW",
            "locale": "zh-TW",
        }
        if return_date is not None:
            params["returnDate"] = return_date.isoformat()

        url = f"https://{self.host}{path}"
        headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.host,
            "accept": "application/json",
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params=params, headers=headers)
        if resp.status_code >= 400:
            logger.warning(
                "skyscanner_search_failed",
                extra={"status": resp.status_code, "path": path},
            )
            raise SkyscannerError(
                f"Skyscanner search failed: {resp.status_code} {resp.text[:200]}"
            )
        return _parse_payload(resp.json())


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _parse_payload(payload: dict) -> list[TicketOffer]:
    data = payload.get("data") or payload
    itineraries = data.get("itineraries") or []
    return [_parse_itinerary(it) for it in itineraries if _parse_itinerary(it) is not None]


def _parse_itinerary(it: dict) -> TicketOffer | None:
    legs = []
    for seg in it.get("legs") or []:
        for stop in seg.get("segments") or [seg]:
            try:
                legs.append(_parse_leg(stop))
            except (KeyError, ValueError, TypeError):
                return None
    if not legs:
        return None

    price_obj = it.get("price") or {}
    raw_price = (
        price_obj.get("raw")
        or price_obj.get("amount")
        or price_obj.get("formatted", "0").replace(",", "").split()[-1]
    )
    try:
        price = round(float(raw_price))
    except (TypeError, ValueError):
        return None

    return TicketOffer(
        offer_id=str(it.get("id", "skyscanner-unknown")),
        legs=tuple(legs),
        total_price=price,
        currency=price_obj.get("currency", "TWD"),
        fare_class=None,
        baggage_through_checked=True,
        issuer="skyscanner",
    )


def _parse_leg(seg: dict) -> FlightLeg:
    origin = seg["origin"]["displayCode"] if isinstance(seg.get("origin"), dict) else seg["origin"]
    dest = seg["destination"]["displayCode"] if isinstance(seg.get("destination"), dict) else seg["destination"]
    dep_at = seg.get("departure") or seg.get("departureDateTime")
    arr_at = seg.get("arrival") or seg.get("arrivalDateTime")
    carriers = seg.get("carriers") or {}
    marketing = carriers.get("marketing") or []
    carrier_code = marketing[0]["alternateId"] if marketing else seg.get("marketingCarrier", "??")
    flight_no = seg.get("flightNumber", "")
    return FlightLeg(
        origin=origin,
        destination=dest,
        departure=datetime.fromisoformat(dep_at),
        arrival=datetime.fromisoformat(arr_at),
        carrier=carrier_code,
        flight_number=f"{carrier_code}{flight_no}",
        cabin=CabinClass.ECONOMY,
        stops=max(0, int(seg.get("stopCount", 0))),
    )


# sanity: it satisfies the Protocol
_: type[FlightOfferProvider] = SkyscannerProvider
