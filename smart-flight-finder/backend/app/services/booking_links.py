"""Deep links to public flight-search sites for a ticket's route and dates.

Offers from the stub provider carry illustrative prices only, and the Amadeus
self-service API has no booking deep link — so every ticket gets search links
that open the same route / dates / pax / cabin on real sites where the live
fare can be checked and booked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from urllib.parse import quote, urlencode

from app.models.enums import CabinClass
from app.services.strategies.base import TicketOffer

_TRIP_CLASS = {
    CabinClass.ECONOMY: "y",
    CabinClass.PREMIUM_ECONOMY: "s",
    CabinClass.BUSINESS: "c",
    CabinClass.FIRST: "f",
}
_SKYSCANNER_CLASS = {
    CabinClass.ECONOMY: "economy",
    CabinClass.PREMIUM_ECONOMY: "premiumeconomy",
    CabinClass.BUSINESS: "business",
    CabinClass.FIRST: "first",
}
_GOOGLE_CLASS = {
    CabinClass.ECONOMY: "economy",
    CabinClass.PREMIUM_ECONOMY: "premium economy",
    CabinClass.BUSINESS: "business class",
    CabinClass.FIRST: "first class",
}


@dataclass(frozen=True, slots=True)
class BookingLink:
    source: str   # "trip_com" | "google_flights" | "skyscanner"
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class _Route:
    origin: str
    destination: str
    depart: date
    return_: date | None


def _route_of(ticket: TicketOffer) -> _Route:
    legs = ticket.legs
    first, last = legs[0], legs[-1]
    if len(legs) >= 2 and last.destination == first.origin:
        # Round trip: the turnaround is the longest ground gap between legs
        # (connections are hours, the stay is days).
        turn = max(
            range(len(legs) - 1),
            key=lambda i: legs[i + 1].departure - legs[i].arrival,
        )
        return _Route(
            origin=first.origin,
            destination=legs[turn].destination,
            depart=first.departure.date(),
            return_=legs[turn + 1].departure.date(),
        )
    return _Route(first.origin, last.destination, first.departure.date(), None)


def _trip_com(r: _Route, adults: int, cabin: CabinClass) -> str:
    params = {
        "dcity": r.origin.lower(),
        "acity": r.destination.lower(),
        "ddate": r.depart.isoformat(),
        "triptype": "rt" if r.return_ else "ow",
        "class": _TRIP_CLASS[cabin],
        "quantity": adults,
        "locale": "zh-TW",
        "curr": "TWD",
    }
    if r.return_:
        params["rdate"] = r.return_.isoformat()
    return f"https://www.trip.com/flights/showfarefirst?{urlencode(params)}"


def _google_flights(r: _Route, adults: int, cabin: CabinClass) -> str:
    q = f"Flights from {r.origin} to {r.destination} on {r.depart.isoformat()}"
    if r.return_:
        q += f" through {r.return_.isoformat()}"
    q += f" {adults} adult{'s' if adults > 1 else ''} {_GOOGLE_CLASS[cabin]}"
    return f"https://www.google.com/travel/flights?q={quote(q)}&hl=zh-TW&curr=TWD"


def _skyscanner(r: _Route, adults: int, cabin: CabinClass) -> str:
    path = f"{r.origin.lower()}/{r.destination.lower()}/{r.depart:%y%m%d}/"
    if r.return_:
        path += f"{r.return_:%y%m%d}/"
    params = urlencode({"adultsv2": adults, "cabinclass": _SKYSCANNER_CLASS[cabin]})
    return f"https://www.skyscanner.com.tw/transport/flights/{path}?{params}"


def booking_links(
    ticket: TicketOffer, *, adults: int = 1, cabin: CabinClass = CabinClass.ECONOMY
) -> list[BookingLink]:
    r = _route_of(ticket)
    return [
        BookingLink("trip_com", "Trip.com", _trip_com(r, adults, cabin)),
        BookingLink("google_flights", "Google Flights", _google_flights(r, adults, cabin)),
        BookingLink("skyscanner", "Skyscanner", _skyscanner(r, adults, cabin)),
    ]
