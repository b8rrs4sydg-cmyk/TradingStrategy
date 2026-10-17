"""Deep links to public flight-search sites for a ticket's route and dates.

Offers from the stub provider carry illustrative prices only, and the Amadeus
self-service API has no booking deep link — so every ticket gets search links
that open the same route / dates / pax / cabin on real sites where the live
fare can be checked and booked.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode

from app.models.enums import CabinClass

if TYPE_CHECKING:  # strategies → schemas → booking_links would be circular
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


# --- multi-city -------------------------------------------------------------
# Tickets priced over several segments (倒買法 包覆票/反向票, 外站四腿票) must
# be searched as the same multi-city itinerary, not as a plain round trip.

_GOOGLE_SEAT = {
    CabinClass.ECONOMY: 1,
    CabinClass.PREMIUM_ECONOMY: 2,
    CabinClass.BUSINESS: 3,
    CabinClass.FIRST: 4,
}
_GOOGLE_TRIP_MULTI_CITY = 3


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _pb_bytes(field: int, payload: bytes) -> bytes:
    return _varint(field << 3 | 2) + _varint(len(payload)) + payload


def _pb_varint(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def google_flights_tfs(
    segments: Sequence[tuple[str, str, date]], *, adults: int, cabin: CabinClass
) -> str:
    """Google Flights ``tfs`` query: base64 of the ``Info`` protobuf.

    Field numbers follow the reverse-engineered schema in the ``fast-flights``
    library: Info{data=3 (FlightData), passengers=8, seat=9, trip=19},
    FlightData{date=2, from_flight=13, to_flight=14}, Airport{airport=2}.
    """

    msg = b"".join(
        _pb_bytes(
            3,
            _pb_bytes(2, day.isoformat().encode())
            + _pb_bytes(13, _pb_bytes(2, o.encode()))
            + _pb_bytes(14, _pb_bytes(2, d.encode())),
        )
        for o, d, day in segments
    )
    msg += _pb_bytes(8, b"".join(_varint(1) for _ in range(adults)))  # ADULT, packed
    msg += _pb_varint(9, _GOOGLE_SEAT[cabin])
    msg += _pb_varint(19, _GOOGLE_TRIP_MULTI_CITY)
    return base64.b64encode(msg).decode()


def _multi_city_links(
    segments: Sequence[tuple[str, str, date]], adults: int, cabin: CabinClass
) -> list[BookingLink]:
    trip = urlencode(
        {
            "dcity": ",".join(o.lower() for o, _, _ in segments),
            "acity": ",".join(d.lower() for _, d, _ in segments),
            "ddate": ",".join(day.isoformat() for _, _, day in segments),
            "triptype": "mt",
            "class": _TRIP_CLASS[cabin],
            "quantity": adults,
            "locale": "zh-TW",
            "curr": "TWD",
        },
        safe=",",
    )
    tfs = google_flights_tfs(segments, adults=adults, cabin=cabin)
    sky_path = "/".join(f"{o.lower()}/{day.isoformat()}/{d.lower()}" for o, d, day in segments)
    sky_q = urlencode({"adultsv2": adults, "cabinclass": _SKYSCANNER_CLASS[cabin]})
    return [
        BookingLink("trip_com", "Trip.com 多段", f"https://www.trip.com/flights/showfarefirst?{trip}"),
        BookingLink(
            "google_flights",
            "Google Flights 多段",
            f"https://www.google.com/travel/flights?tfs={quote(tfs, safe='')}&hl=zh-TW&curr=TWD",
        ),
        BookingLink(
            "skyscanner",
            "Skyscanner 多段",
            f"https://www.skyscanner.com.tw/transport/d/{sky_path}/?{sky_q}",
        ),
    ]


def booking_links(
    ticket: TicketOffer, *, adults: int = 1, cabin: CabinClass = CabinClass.ECONOMY
) -> list[BookingLink]:
    if len(ticket.searched_segments) >= 2:
        return _multi_city_links(ticket.searched_segments, adults, cabin)
    r = _route_of(ticket)
    return [
        BookingLink("trip_com", "Trip.com", _trip_com(r, adults, cabin)),
        BookingLink("google_flights", "Google Flights", _google_flights(r, adults, cabin)),
        BookingLink("skyscanner", "Skyscanner", _skyscanner(r, adults, cabin)),
    ]
